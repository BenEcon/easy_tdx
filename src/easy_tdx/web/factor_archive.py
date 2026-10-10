"""Validate frozen factor research without consulting the current factor registry."""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from easy_tdx.factor.snapshot import restore_input
from easy_tdx.web.research_archive import ArchiveError, _archive_time


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _numeric(value: Any) -> bool:
    return value is None or type(value) in (int, float) and math.isfinite(value)


def _validate_composition(result: dict[str, Any], frames: list[pd.DataFrame]) -> None:
    from easy_tdx.factor.composition import COMPOSITION_VERSION, SCORE_NAME, normalize_composition
    from easy_tdx.factor.research import prepare_frame

    settings, value = result["settings"], result.get("composition")
    config = normalize_composition(settings.get("composition"), settings["factors"])
    if config is None:
        _require(value is None, "组合结果没有对应配置")
        return
    if not isinstance(value, dict) or value.get("version") != COMPOSITION_VERSION:
        raise ValueError("组合版本缺失")
    _require(
        value["config"] == config
        and value["score_name"] == SCORE_NAME
        and value["trade_eligible"] is False,
        "组合配置、标识或研究边界不符",
    )
    symbols = [f"{s['market']}:{s['code']}" for s in settings["stocks"]]
    _require(value["symbols"] == symbols, "组合标的顺序不符")
    names = [c["name"] for c in config["components"]]
    total = math.fsum(c["weight"] for c in config["components"])
    effective = [{**c, "normalized_weight": c["weight"] / total} for c in config["components"]]
    _require(value["effective_components"] == effective, "组合实际权重不符")
    _require(
        value["policy"]
        == {
            "pool": "same_date_complete_intersection",
            "minimum_assets": 5,
            "missing": "no_imputation_no_weight_renormalization",
            "fit": "fixed_user_weights_no_return_fitting",
        },
        "组合规则不完整",
    )
    dates = pd.DatetimeIndex(sorted(set().union(*(set(prepare_frame(f).index) for f in frames))))
    expected_dates = dates.strftime("%Y-%m-%d").tolist()
    _require(
        isinstance(value["error"], str) and bool(value["error"]) or value["error"] is None,
        "组合错误格式无效",
    )
    _require(
        [r["date"] for r in value["scores"]] == expected_dates
        and [r["date"] for r in value["coverage"]] == expected_dates,
        "组合评分或覆盖日期不完整",
    )
    for row, coverage in zip(value["scores"], value["coverage"], strict=True):
        _require(
            len(row["values"]) == len(symbols)
            and all(_numeric(v) and (v is None or abs(v) <= 1 + 1e-12) for v in row["values"]),
            "组合评分范围或数量无效",
        )
        n = sum(v is not None for v in row["values"])
        _require(
            type(coverage["complete_assets"]) is int
            and 0 <= coverage["complete_assets"] <= len(symbols)
            and coverage["scored_assets"] == n
            and (n == 0 or n >= 5),
            "组合覆盖计数不符",
        )
        _require(
            n
            == (
                coverage["complete_assets"]
                if coverage["complete_assets"] >= 5 and value["error"] is None
                else 0
            ),
            "组合静默缩小样本",
        )
        _require(
            isinstance(coverage["constant_components"], list)
            and set(coverage["constant_components"]) <= set(names),
            "组合常数记录无效",
        )
    _require([r["code"] for r in value["latest"]] == symbols, "组合最新评分标的不完整")
    for i, row in enumerate(value["latest"]):
        _require(
            row["score"] == value["scores"][-1]["values"][i]
            and [c["name"] for c in row["components"]] == names,
            "组合最新评分或组成因子不符",
        )
        for component, weight in zip(row["components"], effective, strict=True):
            _require(
                all(_numeric(component[k]) for k in ("raw", "rank", "contribution")),
                "组合贡献值无效",
            )
            rank, contribution = component["rank"], component["contribution"]
            if row["score"] is None:
                _require(rank is None and contribution is None, "缺失组合不能有部分贡献")
            else:
                _require(
                    rank is not None
                    and component["raw"] is not None
                    and abs(rank) <= 1 + 1e-12
                    and contribution is not None
                    and math.isclose(
                        contribution,
                        rank * weight["direction"] * weight["normalized_weight"],
                        abs_tol=1e-12,
                    ),
                    "组合贡献与权重不一致",
                )
        if row["score"] is not None:
            _require(
                math.isclose(
                    row["score"],
                    math.fsum(c["contribution"] for c in row["components"]),
                    abs_tol=1e-12,
                ),
                "组合贡献之和不符",
            )
    _require(
        [r["name"] for r in value["reports"]] == [SCORE_NAME]
        and isinstance(value["limitations"], list)
        and value["limitations"],
        "组合报告或说明缺失",
    )
    view = {
        **result,
        "reports": value["reports"],
        "validation": value["validation"],
        "horizon_comparison": value["horizon_comparison"],
        "settings": {**settings, "horizons": settings.get("horizons") or [settings["horizon"]]},
    }
    _validate_horizon_comparison(view, frames)


def _validate_horizon_comparison(result: dict[str, Any], frames: list[pd.DataFrame]) -> None:
    from easy_tdx.factor.horizons import HORIZON_VERSION, normalize_horizons
    from easy_tdx.factor.research import prepare_frame

    settings, value = result["settings"], result.get("horizon_comparison")
    selection = settings.get("horizons")
    if selection is None:
        _require(value is None, "多远期结果缺少对应选择")
        return
    horizons = normalize_horizons(settings["horizon"], selection)
    _require(selection == horizons, "远期窗口顺序不规范")
    if not isinstance(value, dict):
        raise ValueError("多远期结果缺失")
    _require(
        isinstance(value, dict)
        and value.get("version") == HORIZON_VERSION
        and value.get("horizons") == horizons
        and value.get("sample_policy") == "each_horizon_own_complete_labels",
        "多远期版本、配置或样本口径不一致",
    )
    results = value["results"]
    _require(
        isinstance(results, list) and [r["horizon"] for r in results] == horizons,
        "远期结果缺失或重复",
    )
    dates = pd.DatetimeIndex(sorted(set().union(*(set(prepare_frame(f).index) for f in frames))))
    _require(len(dates) <= 800, "多远期合并日期超限")
    expected_dates = dates.strftime("%Y-%m-%d").tolist()
    names = [r["name"] for r in result["reports"]]
    for item in results:
        h, reports = item["horizon"], item["reports"]
        _require(
            type(h) is int and isinstance(reports, list) and [r["name"] for r in reports] == names,
            "远期因子报告缺失",
        )
        for r in reports:
            _require(
                all(
                    _numeric(r[k])
                    for k in (
                        "coverage",
                        "ic_mean",
                        "rank_ic_mean",
                        "rank_ic_ir",
                        "positive_rate",
                        "spread",
                    )
                ),
                "远期统计数值无效",
            )
            _require(
                type(r["observations"]) is int
                and 0 <= r["observations"] <= len(dates)
                and type(r["layer_dates"]) is int
                and 0 <= r["layer_dates"] <= len(dates)
                and isinstance(r["diagnostics"], dict),
                "远期有效计数或诊断无效",
            )
            _require(
                len(r["layer_means"]) == settings["groups"]
                and all(_numeric(v) for v in r["layer_means"]),
                "远期分层不完整",
            )
            _require([d["date"] for d in r["daily"]] == expected_dates, "远期日期不完整")
            for i, day in enumerate(r["daily"]):
                _require(
                    day["label_end"] == (expected_dates[i + h] if i + h < len(dates) else None),
                    "远期收益终点不正确",
                )
                _require(
                    all(
                        _numeric(day[k])
                        for k in ("ic", "rank_ic", "rolling_rank_ic", "layer_spread")
                    )
                    and len(day["layers"]) == settings["groups"]
                    and all(_numeric(v) for v in day["layers"]),
                    "远期逐日数值无效",
                )
        view = {
            **result,
            "settings": {**settings, "horizon": h},
            "reports": reports,
            "validation": item["validation"],
        }
        _validate_time_validation(view, frames)
        if h == settings["horizon"]:
            _require(
                reports == result["reports"] and item["validation"] == result.get("validation"),
                "主窗口结果与多远期结果不一致",
            )


def _validate_time_validation(result: dict[str, Any], frames: list[pd.DataFrame]) -> None:
    """Validate the frozen split layout only; never run factor or IC calculations."""
    from easy_tdx.factor.research import prepare_frame
    from easy_tdx.factor.validation import normalize_validation, validation_plan

    config = result["settings"].get("validation")
    value = result.get("validation")
    if config is None:
        _require(value is None, "时间划分结果没有对应配置")
        return
    if not isinstance(value, dict):
        raise ValueError("时间划分结果缺失")
    config = normalize_validation(config)
    _require(
        isinstance(value, dict) and value.get("version") == "factor-time-validation-v1",
        "时间划分版本缺失",
    )
    _require(value.get("config") == config, "时间划分配置与结果不一致")
    dates = pd.DatetimeIndex(sorted(set().union(*(set(prepare_frame(f).index) for f in frames))))
    horizon, groups = result["settings"]["horizon"], result["settings"]["groups"]
    plan = validation_plan(dates, horizon, config)
    names = [r["name"] for r in result["reports"]]
    expected_dates = dates.strftime("%Y-%m-%d").tolist()
    _require(
        all([r["date"] for r in report["daily"]] == expected_dates for report in result["reports"]),
        "全样本日期与原输入不一致",
    )
    folds = value.get("folds")
    if not isinstance(folds, list) or len(folds) != len(plan):
        raise ValueError("滚动窗口缺失或重复")

    def summaries(reports: Any) -> None:
        _require(
            isinstance(reports, list) and [r["name"] for r in reports] == names,
            "分区因子报告不完整",
        )
        for r in reports:
            _require(
                all(
                    _numeric(r[k])
                    for k in (
                        "coverage",
                        "ic_mean",
                        "rank_ic_mean",
                        "rank_ic_ir",
                        "positive_rate",
                        "spread",
                    )
                ),
                "分区统计值无效",
            )
            _require(
                type(r["observations"]) is int
                and r["observations"] >= 0
                and type(r["layer_dates"]) is int
                and r["layer_dates"] >= 0,
                "分区有效计数无效",
            )
            _require(
                len(r["layer_means"]) == groups
                and all(_numeric(v) for v in r["layer_means"])
                and isinstance(r["diagnostics"], dict),
                "分区分层或诊断缺失",
            )

    test_dates: list[tuple[int, int, int]] = []
    for i, (fold, segments) in enumerate(zip(folds, plan, strict=True), 1):
        _require(fold["id"] == i and len(fold["phases"]) == 3, "窗口编号或区间缺失")
        for phase, (key, begin, end) in zip(fold["phases"], segments, strict=True):
            _require(
                phase["phase"] == key
                and phase["start"] == expected_dates[begin]
                and phase["end"] == expected_dates[end - 1],
                "分区日期与原配置不一致",
            )
            _require(
                phase["date_count"] == end - begin
                and phase["purged_dates"] == min(horizon, end - begin)
                and phase["label_eligible_dates"] == max(0, end - begin - horizon),
                "边界剔除计数不一致",
            )
            summaries(phase["reports"])
            if key == "test":
                test_dates.extend((i, pos, end) for pos in range(begin, end))
    summaries(value.get("test_reports"))
    for report in value["test_reports"]:
        _require(len(report["daily"]) == len(test_dates), "测试期逐日结果缺失")
        for row, (fold_id, pos, end) in zip(report["daily"], test_dates, strict=True):
            _require(
                row["date"] == expected_dates[pos] and row["fold"] == fold_id,
                "测试期重叠或日期错误",
            )
            _require(
                all(_numeric(row[k]) for k in ("ic", "rank_ic", "rolling_rank_ic", "layer_spread"))
                and len(row["layers"]) == groups
                and all(_numeric(v) for v in row["layers"]),
                "测试期逐日统计无效",
            )
            if pos + horizon >= end:
                _require(
                    row["n"] == 0
                    and row["ic"] is None
                    and row["rank_ic"] is None
                    and row["layer_spread"] is None
                    and all(v is None for v in row["layers"]),
                    "测试期越界标签未剔除",
                )
    _require(
        isinstance(value.get("policy"), dict) and isinstance(value.get("limitations"), list),
        "时间划分口径缺失",
    )


def validate_factor_archive(payload: dict[str, Any]) -> None:
    """Input integrity is not an attestation of market provenance or correct results."""
    try:
        _require(payload["format"] == "factor-research-v1", "不支持此因子存档版本")
        _require(payload["mode"] in ("series", "evaluation"), "研究模式无效")
        _require(
            isinstance(payload["title"], str) and 0 < len(payload["title"].strip()) <= 120,
            "存档标题无效",
        )
        _archive_time(payload["savedAt"], clock=True)
        result = payload["result"]
        _require(isinstance(result, dict), "缺少原始结果")
        settings, definitions, snapshots = (
            result[k] for k in ("settings", "factor_definitions", "input_snapshots")
        )
        _require(isinstance(settings, dict) and isinstance(definitions, dict), "缺少配置或冻结公式")
        names = settings["factors"]
        evaluation = payload["mode"] == "evaluation"
        _require(
            isinstance(names, list) and 1 <= len(names) <= (4 if evaluation else 12), "因子数量无效"
        )
        _require(
            all(isinstance(n, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,100}", n) for n in names)
            and len(set(names)) == len(names),
            "因子标识无效或重复",
        )
        _require(set(definitions) == set(names), "冻结公式与选择不一致")
        for name in names:
            d = definitions[name]
            _require(isinstance(d, dict) and d.get("name") == name, "公式标识不一致")
            for field in ("formula", "implementation_version", "source", "catalog_version"):
                _require(isinstance(d.get(field), str) and d[field], f"缺少公式 {field}")
            _require(isinstance(d.get("resolved_parameters"), dict), "缺少实际参数")
            supplied = settings.get("factor_parameters", {})
            _require(isinstance(supplied, dict), "参数配置无效")
            for key, val in supplied.get(name, {}).items():
                _require(d["resolved_parameters"].get(key) == val, "保存配置与实际参数不一致")
            _require(
                isinstance(d.get("formula_sha256"), str)
                and re.fullmatch(r"[a-f0-9]{64}", d["formula_sha256"]),
                "缺少公式摘要",
            )
        _require(settings["adjust"] in {"NONE", "QFQ", "HFQ"}, "复权配置无效")
        _require(type(settings["count"]) is int and 60 <= settings["count"] <= 800, "历史长度无效")
        _require(
            isinstance(snapshots, list)
            and (5 <= len(snapshots) <= 20 if evaluation else len(snapshots) == 1),
            "原始输入数量不完整",
        )
        expected = (
            [f"{s['market']}:{s['code']}" for s in settings["stocks"]]
            if evaluation
            else [f"{settings['market']}:{settings['code']}"]
        )
        _require(
            len(set(expected)) == len(expected) and [s["symbol"] for s in snapshots] == expected,
            "股票池与原始输入不一致",
        )
        frames = [restore_input(s) for s in snapshots]
        for frame in frames:
            _require(len(frame) <= settings["count"], "输入行数超过所选范围")
            metadata = frame.attrs.get("snapshot_metadata")
            _require(
                isinstance(metadata, dict) and metadata.get("actual_adjust") == settings["adjust"],
                "原行情复权来源不一致",
            )
            _require(metadata.get("category") == settings["category"], "原行情周期不一致")
            time_key = "datetime" if "datetime" in frame else "date"
            dates = pd.to_datetime(frame[time_key], errors="raise")
            _require(
                not dates.isna().any()
                and dates.is_monotonic_increasing
                and not dates.duplicated().any(),
                "原始行情时间缺失、重复或乱序",
            )
        _require(
            isinstance(result.get("errors"), dict)
            and set(result["errors"]).issubset(names)
            and all(isinstance(v, str) and v for v in result["errors"].values()),
            "错误记录不完整",
        )
        _require(
            isinstance(result.get("input_fingerprint"), str)
            and re.fullmatch(r"[a-f0-9]{64}", result["input_fingerprint"]),
            "缺少计算指纹",
        )
        if evaluation:
            provenance = result["provenance"]
            _require(
                isinstance(provenance, list) and len(provenance) == len(frames),
                "原始来源列表不完整",
            )
            for i, item in enumerate(provenance):
                _require(
                    item["code"] == expected[i]
                    and item["count"] == len(frames[i])
                    and item["metadata"] == frames[i].attrs.get("snapshot_metadata"),
                    "原始来源与输入不一致",
                )
            _require(
                result.get("version") == "factor-cross-section-v1"
                and result.get("trade_eligible") is False,
                "检验版本或研究边界缺失",
            )
            _require(
                settings["category"] == "DAY"
                and settings["horizon"] in (1, 5, 10, 20)
                and settings["groups"] in (3, 5)
                and settings["preprocess"] in ("raw", "mad_zscore"),
                "检验配置无效",
            )
            _require(
                result["assets"] == len(frames) and isinstance(result["reports"], list),
                "股票池报告不完整",
            )
            good = [r["name"] for r in result["reports"]]
            _require(len(set(good)) == len(good), "检验报告重复")
            for report in result["reports"]:
                _require(
                    isinstance(report["daily"], list)
                    and len(report["daily"]) <= 16000
                    and isinstance(report["layer_means"], list)
                    and len(report["layer_means"]) == settings["groups"],
                    "检验序列或分层不完整",
                )
                for day in report["daily"]:
                    _archive_time(day["date"])
                    _require(
                        all(_numeric(day[k]) for k in ("ic", "rank_ic", "rolling_rank_ic")),
                        "相关系数格式无效",
                    )
                    _require(
                        isinstance(day["layers"], list)
                        and len(day["layers"]) == settings["groups"]
                        and all(_numeric(v) for v in day["layers"]),
                        "分层格式无效",
                    )
            _require(
                isinstance(result["latest"], list)
                and isinstance(result["redundancy"], list)
                and isinstance(result["limitations"], list),
                "检验明细缺失",
            )
            _validate_time_validation(result, frames)
            _validate_horizon_comparison(result, frames)
            _validate_composition(result, frames)
        else:
            good = result["computed"]
            _require(
                isinstance(good, list)
                and all(isinstance(n, str) for n in good)
                and len(set(good)) == len(good),
                "已计算因子列表无效",
            )
            rows = result["rows"]
            _require(
                isinstance(rows, list)
                and len(rows) == len(frames[0]) == result["count"] == result["input_count"]
                and result["output_truncated"] is False,
                "结果与原始行情行数不一致",
            )
            input_dates = pd.to_datetime(
                frames[0]["datetime" if "datetime" in frames[0] else "date"]
            )
            for i, row in enumerate(rows):
                _require(
                    pd.Timestamp(row["datetime"]) == input_dates.iloc[i]
                    and all(n in row and _numeric(row[n]) for n in good),
                    "因子结果索引或数值不完整",
                )
            _require(
                isinstance(result["diagnostics"], dict) and set(result["diagnostics"]) == set(good),
                "有效值诊断缺失",
            )
        _require(
            set(good).isdisjoint(result["errors"])
            and set(good) | set(result["errors"]) == set(names),
            "存在未保存结果或失败原因的因子",
        )
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        raise ArchiveError(422, f"因子原档不完整或不一致：{exc}") from exc
