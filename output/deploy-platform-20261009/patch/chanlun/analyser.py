"""缠论分析器主入口。

ChanlunAnalyser 接收 easy_tdx 的 K 线 DataFrame，
内部执行完整的缠论计算管道：
K线合并 → 分型识别 → 笔计算 → 中枢计算 → 线段 → 买卖点 → 背驰。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from easy_tdx.chanlun.anchors import extreme_date
from easy_tdx.chanlun.beichi import check_bi_beichi  # noqa: F401
from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.decomposition import decompose_base_chain
from easy_tdx.chanlun.divergence_signals import (
    indicator_events,
    link_wave_families,
    special_wave_events,
    wave_events,
)
from easy_tdx.chanlun.engineering_completion import link_engineering_completions
from easy_tdx.chanlun.engineering_trends import (
    engineering_movement_hierarchy,
    engineering_trend_hierarchy,
)
from easy_tdx.chanlun.expansion_regrouping import expansion_regrouping
from easy_tdx.chanlun.extension_recursion import extension_hierarchy
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.input_data import prepare_frame, require_chronological
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.layered_ownership import layered_movement_ownership
from easy_tdx.chanlun.macd import calc_macd  # noqa: F401
from easy_tdx.chanlun.mmd import find_mmds  # noqa: F401
from easy_tdx.chanlun.ownership_history import OwnershipHistoryMode
from easy_tdx.chanlun.regrouping_versions import regrouping_versions
from easy_tdx.chanlun.released_recursion import released_movement_snapshot
from easy_tdx.chanlun.structure import StructuralCentre, find_structural_centres
from easy_tdx.chanlun.structure_signals import (
    StructuralSignal,
    structure_signals,
    to_chart_signals,
)
from easy_tdx.chanlun.types import BC, BI, FX, MMD, XD, ZS, CLKline, Kline
from easy_tdx.chanlun.xd import find_unfinished_xd, find_xds
from easy_tdx.chanlun.zs import find_zss


def _df_to_klines(df: pd.DataFrame) -> list[Kline]:
    """将 easy_tdx K 线 DataFrame 转为缠论 Kline 列表。

    期望 DataFrame 包含列：datetime, open, close, high, low, vol
    """
    klines: list[Kline] = []
    for i, row in enumerate(df.itertuples()):
        dt = row.datetime
        row_any: Any = row  # avoid pandas-stubs vs bare pandas type mismatch
        vol = getattr(row, "vol", 0.0) or 0.0
        klines.append(
            Kline(
                index=i,
                date=dt,
                open=float(row_any.open),
                close=float(row_any.close),
                high=float(row_any.high),
                low=float(row_any.low),
                amount=float(vol),
                is_closed=bool(getattr(row_any, "is_closed", True)),
            )
        )
    return klines


@dataclass
class ChanlunResult:
    """缠论分析结果。"""

    code: str = ""
    frequency: str = ""
    klines: list[Kline] = field(default_factory=list)
    cklines: list[CLKline] = field(default_factory=list)
    fractals: list[FX] = field(default_factory=list)
    bis: list[BI] = field(default_factory=list)
    zss: list[ZS] = field(default_factory=list)
    xds: list[XD] = field(default_factory=list)
    unfinished_xd: XD | None = None
    mmds: list[MMD] = field(default_factory=list)
    bcs: list[BC] = field(default_factory=list)
    wave_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    macd: dict[str, list[float]] = field(default_factory=dict)
    structural_centres: list[StructuralCentre] = field(default_factory=list)
    structural_signals: list[StructuralSignal] = field(default_factory=list)

    def _fmt_dt(self, dt: datetime) -> str:
        """按 frequency 自适应格式化日期。

        分钟级别（1/5/15/30/60min）输出完整时分 YYYY-MM-DD HH:MM，
        日/周/月/年级别只输出日期 YYYY-MM-DD（无多余 00:00）。
        frequency 来自 CLI 原始值（如 5MIN/30MIN）或 Web 映射值（5min/30min），
        统一转小写后判断是否含 'min'。
        """
        fmt = "%Y-%m-%d %H:%M" if "min" in self.frequency.lower() else "%Y-%m-%d"
        return dt.strftime(fmt)

    @staticmethod
    def _fx_dt(fx: FX) -> datetime:
        """返回分型极值真正所在的原始 K 线时间。

        包含处理后的 CLKline.date 是合并区间最后一根 K 线时间，但分型高低值
        可能来自区间内更早的一根。图表若直接使用 CLKline.date，会让端点价格
        落在错误蜡烛上。这里按分型类型回溯原始 K 线并吸附到真实极值位置。
        """
        return extreme_date(fx)

    def _wave_audit_dict(self, record: dict[str, Any]) -> dict[str, Any]:
        """Serialize frozen checkpoints and research comparisons without sharing state."""
        if not record:
            return {}
        result = deepcopy(record)
        date_keys = (
            "original_a_start",
            "original_a_end",
            "a_start",
            "a_end",
            "b_start",
            "b_end",
            "c_start",
            "c_end",
            "known_index",
            "first_checked_index",
            "first_candidate_index",
        )
        result["dates"] = {
            key: self._fmt_dt(self.klines[value].date)
            for key, value in record.items()
            if key in date_keys and isinstance(value, int) and 0 <= value < len(self.klines)
        }
        for check in result.get("checks", []):
            check["dates"] = {
                key: self._fmt_dt(self.klines[value].date)
                for key, value in check["values"].items()
                if key.endswith("_index")
                and isinstance(value, int)
                and 0 <= value < len(self.klines)
            }
        for rejection in result.get("rejections", []):
            rejection["from_date"] = self._fmt_dt(self.klines[rejection["from_index"]].date)
            rejection["through_date"] = self._fmt_dt(self.klines[rejection["through_index"]].date)
        result["comparisons"] = [
            self._wave_audit_dict(item) for item in record.get("comparisons", [])
        ]
        return result

    def to_dict(self, *, ownership_history: OwnershipHistoryMode = "full") -> dict[str, Any]:
        """Export an independent JSON-ready snapshot, including nested evidence.

        Callers may annotate the payload before encoding or cache an earlier
        export. Neither may share mutable evidence with this result or another
        export. Copy the small evidence trees, not the full candle/line graph.

        Opt-in summary delivery keeps complete current ownership records and
        every historical address; omitted detail requires original-bar replay.
        """
        if ownership_history not in ("full", "summary"):
            raise ValueError("ownership_history must be full or summary")
        segments_by_id = {segment.index: segment for segment in self.xds}
        pending = self.unfinished_xd
        unfinished = (
            None
            if pending is None
            else {
                "index": pending.index,
                "direction": pending.direction.value,
                "start_date": self._fmt_dt(self._fx_dt(pending.start)),
                "end_date": self._fmt_dt(self._fx_dt(pending.end)),
                "start_value": round(pending.start.val, 2),
                "end_value": round(pending.end.val, 2),
                "high": round(pending.high, 2),
                "low": round(pending.low, 2),
                "confirmed_index": None,
                "confirmed_date": None,
                "done": False,
                "evidence": deepcopy(pending.evidence),
            }
        )
        decomposition = decompose_base_chain(self.xds, len(self.klines))
        for block in decomposition["blocks"]:
            block["known_date"] = self._fmt_dt(self.klines[block["known_index"]].date)
            for key in ("start", "end"):
                block[f"{key}_date"] = self._fmt_dt(self.klines[block[f"{key}_index"]].date)
        hierarchy = extension_hierarchy(self.xds, len(self.klines))
        trend_hierarchy = engineering_trend_hierarchy(self.xds, self.klines, self.macd)
        movement_hierarchy = engineering_movement_hierarchy(self.xds, self.klines, self.macd)
        ownership = layered_movement_ownership(
            self.xds,
            self.klines,
            self.macd,
            movement_hierarchy,
            ownership_history=ownership_history,
        )
        recursive_ownership = layered_movement_ownership(
            self.xds,
            self.klines,
            self.macd,
            movement_hierarchy,
            nested=True,
            ownership_history=ownership_history,
        )
        released_recursion = released_movement_snapshot(self.xds, self.klines, self.macd)
        for view in (trend_hierarchy, movement_hierarchy):
            for level in view["levels"]:
                for trend in level["types"]:
                    for key in ("start", "end", "known", "divergence_known"):
                        trend[f"{key}_date"] = self._fmt_dt(self.klines[trend[f"{key}_index"]].date)

        def date_recursive_structure(value: Any) -> None:
            if isinstance(value, list):
                for child in value:
                    date_recursive_structure(child)
            elif isinstance(value, dict):
                for key, child in list(value.items()):
                    if key in (
                        "start_index",
                        "end_index",
                        "known_index",
                        "formed_index",
                        "exited_index",
                        "admitted_index",
                        "unit_confirmed_index",
                        "as_of_index",
                        "original_known_index",
                        "ownership_known_index",
                        "context_known_index",
                        "divergence_known_index",
                        "current_owner_known_index",
                    ):
                        value[key.replace("_index", "_date")] = (
                            self._fmt_dt(self.klines[child].date) if child is not None else None
                        )
                    else:
                        date_recursive_structure(child)

        date_recursive_structure(trend_hierarchy["structure_layers"])
        date_recursive_structure(movement_hierarchy["structure_layers"])
        date_recursive_structure(ownership)
        date_recursive_structure(recursive_ownership)
        date_recursive_structure(released_recursion)

        def date_proof(proof: dict[str, Any]) -> None:
            for key in ("start", "end", "known"):
                proof[f"{key}_date"] = self._fmt_dt(self.klines[proof[f"{key}_index"]].date)
            for admission in proof.get("member_admissions", []):
                for key in ("segment_confirmed", "admitted"):
                    admission[f"{key}_date"] = self._fmt_dt(
                        self.klines[admission[f"{key}_index"]].date
                    )
            for child in proof["children"]:
                date_proof(child)

        for proof in hierarchy["proofs"]:
            date_proof(proof)
        regrouping = expansion_regrouping(self.xds, len(self.klines))
        for event in regrouping["candidates"]:
            event["known_date"] = (
                self._fmt_dt(self.klines[event["known_index"]].date)
                if event["known_index"] is not None
                else None
            )
            for part in event["parts"]:
                for key in ("start", "end", "known"):
                    part[f"{key}_date"] = self._fmt_dt(self.klines[part[f"{key}_index"]].date)

        def date_audit(audit: dict[str, Any]) -> None:
            audit["as_of_date"] = self._fmt_dt(self.klines[audit["as_of_index"]].date)
            for part in audit["parts"]:
                known = part["opposite_known_index"]
                part["opposite_known_date"] = (
                    self._fmt_dt(self.klines[known].date) if known is not None else None
                )
                if part["opposite_evidence"] is not None:
                    evidence = part["opposite_evidence"]
                    for key in ("start", "end", "known"):
                        evidence[f"{key}_date"] = self._fmt_dt(
                            self.klines[evidence[f"{key}_index"]].date
                        )
                linked = part.get("engineering_completion")
                if linked is not None:
                    linked["known_date"] = self._fmt_dt(self.klines[linked["known_index"]].date)

        for audit in regrouping["completion_audits"]:
            date_audit(audit)
        versions = link_engineering_completions(
            regrouping_versions(self.xds, len(self.klines)), movement_hierarchy
        )

        def date_cover(cover: dict[str, Any]) -> None:
            cover["as_of_date"] = self._fmt_dt(self.klines[cover["as_of_index"]].date)
            for item in cover["blocks"] + cover["conflicts"]:
                item["known_date"] = self._fmt_dt(self.klines[item["known_index"]].date)

        for case in versions["cases"]:
            date_cover(case["mixed_source_cover"])
            date_audit(case["completion_audit"])
            for key in ("formation_known", "as_of"):
                case[f"{key}_date"] = self._fmt_dt(self.klines[case[f"{key}_index"]].date)
            for revision in case["revisions"]:
                date_cover(revision["mixed_source_cover"])
                date_audit(revision["completion_audit"])
                revision["known_date"] = self._fmt_dt(self.klines[revision["known_index"]].date)
                for part in revision["parts"]:
                    for centre in part.get("centre_chain", []):
                        centre["formed_date"] = self._fmt_dt(
                            self.klines[centre["formed_index"]].date
                        )
                    for key in ("start", "end", "known"):
                        part[f"{key}_date"] = self._fmt_dt(self.klines[part[f"{key}_index"]].date)
        from easy_tdx.chanlun.pen_consolidation import recent_pen_consolidations

        return {
            "macd": deepcopy(self.macd),
            "pen_consolidations": recent_pen_consolidations(self.bis),
            "code": self.code,
            "frequency": self.frequency,
            "kline_count": len(self.klines),
            "ckline_count": len(self.cklines),
            "fractal_count": len(self.fractals),
            "bi_count": len(self.bis),
            "zs_count": len(self.zss),
            "xd_count": len(self.xds),
            "unfinished_xd": unfinished,
            "mmd_count": len(self.mmds),
            "bc_count": len(self.bcs),
            "base_decomposition": decomposition,
            "extension_hierarchy": hierarchy,
            "engineering_trend_hierarchy": trend_hierarchy,
            "engineering_movement_hierarchy": movement_hierarchy,
            "layered_movement_ownership": ownership,
            "recursive_movement_ownership": recursive_ownership,
            "released_movement_recursion": released_recursion,
            "expansion_regrouping": regrouping,
            "regrouping_versions": versions,
            "structure_metadata": {
                "version": "segment-centres-v1-preview",
                "display_frequency": self.frequency,
                "base_unit": "confirmed_segment",
                "recursive_levels_ready": False,
                "engineering_trend_recursion_ready": True,
                "engineering_trend_recursion_rule": trend_hierarchy["rule"],
                "engineering_movement_recursion_ready": True,
                "engineering_movement_recursion_rule": movement_hierarchy["rule"],
                "initial_unresolved_bars": (
                    self.cklines[0].klines[0].index
                    if self.cklines and self.cklines[0].klines
                    else 0
                ),
                "extension_regrouping_ready": True,
                "current_regrouping_revisable": True,
                "legacy_zss_source": "pen_overlap_auxiliary",
                "signals_source": "confirmed_segment_base_v1",
                "structural_signals_scope": "base_layer_research_preview",
                "trend_signal_level_policy": "unpromoted_centres_at_confirmation_v1",
                "centre_relation_scope": "committed_base_members_not_recursive_types",
            },
            "structural_centres": [
                {
                    **asdict(centre),
                    "relation_history": [
                        {
                            **deepcopy(event),
                            "known_date": self._fmt_dt(self.klines[event["known_index"]].date),
                        }
                        for event in centre.relation_history
                    ],
                    "transitions": [
                        {
                            **transition,
                            "known_date": self._fmt_dt(self.klines[transition["known_index"]].date),
                        }
                        for transition in centre.transitions
                    ],
                    "line_count": len(centre.member_segments),
                    "done": centre.state == "exited",
                    "start_date": self._fmt_dt(
                        self._fx_dt(segments_by_id[centre.seed_segments[0]].start)
                    ),
                    "end_date": self._fmt_dt(
                        self._fx_dt(
                            segments_by_id[
                                centre.return_segment
                                if centre.return_segment is not None
                                else centre.departure_segment
                                if centre.departure_segment is not None
                                else centre.member_segments[-1]
                            ].end
                        )
                    ),
                    "formed_date": self._fmt_dt(self.klines[centre.formed_index].date),
                    "exited_date": self._fmt_dt(self.klines[centre.exited_index].date)
                    if centre.exited_index is not None
                    else None,
                }
                for centre in self.structural_centres
            ],
            "structural_signals": [
                {
                    **asdict(signal),
                    "date": self._fmt_dt(self.klines[signal.signal_index].date),
                    "confirmed_date": self._fmt_dt(self.klines[signal.confirmed_index].date),
                }
                for signal in self.structural_signals
            ],
            "bis": [
                {
                    "index": bi.index,
                    "direction": bi.direction.value,
                    "start_date": self._fmt_dt(self._fx_dt(bi.start)),
                    "end_date": self._fmt_dt(self._fx_dt(bi.end)),
                    "start_value": round(bi.start.val, 2),
                    "end_value": round(bi.end.val, 2),
                    "high": round(bi.high, 2),
                    "low": round(bi.low, 2),
                    "done": bi.is_done(),
                    "structurally_confirmed": bi.confirmed_index is not None,
                    "confirmed_index": bi.confirmed_index,
                    "confirmed_date": self._fmt_dt(self.klines[bi.confirmed_index].date)
                    if bi.confirmed_index is not None
                    else None,
                }
                for bi in self.bis
            ],
            "zss": [
                {
                    "index": zs.index,
                    "zg": round(zs.zg, 2),
                    "zd": round(zs.zd, 2),
                    "gg": round(zs.gg, 2),
                    "dd": round(zs.dd, 2),
                    "line_count": zs.line_count,
                    "start_date": self._fmt_dt(self._fx_dt(zs.start)) if zs.start else None,
                    "end_date": self._fmt_dt(self._fx_dt(zs.end)) if zs.end else None,
                    "done": zs.done,
                }
                for zs in self.zss
            ],
            "xds": [
                {
                    "index": xd.index,
                    "direction": xd.direction.value,
                    "start_date": self._fmt_dt(self._fx_dt(xd.start)),
                    "end_date": self._fmt_dt(self._fx_dt(xd.end)),
                    "start_value": round(xd.start.val, 2),
                    "end_value": round(xd.end.val, 2),
                    "high": round(xd.high, 2),
                    "low": round(xd.low, 2),
                    "confirmed_index": xd.confirmed_index,
                    "confirmed_date": self._fmt_dt(self.klines[xd.confirmed_index].date)
                    if xd.confirmed_index is not None and xd.confirmed_index < len(self.klines)
                    else None,
                    "evidence": deepcopy(xd.evidence),
                }
                for xd in self.xds
            ],
            "mmds": [
                {
                    "type": mmd.mmd_type.value,
                    "date": self._fmt_dt(self._fx_dt(mmd.bi.end)) if mmd.bi else None,
                    "msg": mmd.msg,
                    "source": mmd.source,
                    "confirmed_index": mmd.confirmed_index,
                    "evidence": deepcopy(mmd.evidence),
                    "confirmed_date": self._fmt_dt(self.klines[mmd.confirmed_index].date)
                    if mmd.confirmed_index is not None
                    else None,
                }
                for mmd in self.mmds
            ],
            "wave_diagnostics": [self._wave_audit_dict(record) for record in self.wave_diagnostics],
            "bcs": [
                {
                    "type": bc.bc_type.value,
                    "bc": bc.bc,
                    "curr_date": self._fmt_dt(self.klines[bc.signal_index].date)
                    if bc.signal_index is not None
                    else self._fmt_dt(self._fx_dt(bc.curr.end))
                    if bc.curr
                    else None,
                    "prev_date": self._fmt_dt(self.klines[bc.reference_index].date)
                    if bc.reference_index is not None
                    else self._fmt_dt(self._fx_dt(bc.prev.end))
                    if bc.prev
                    else None,
                    "detected_date": self._fmt_dt(self.klines[bc.detected_index].date)
                    if bc.detected_index is not None
                    else None,
                    "detected_index": bc.detected_index,
                    "confirmed_date": self._fmt_dt(self.klines[bc.confirmed_index].date)
                    if bc.confirmed_index is not None
                    else None,
                    "preliminary_date": self._fmt_dt(self.klines[bc.preliminary_index].date)
                    if bc.preliminary_index is not None
                    else None,
                    "preliminary_index": bc.preliminary_index,
                    "invalidated_date": self._fmt_dt(self.klines[bc.invalidated_index].date)
                    if bc.invalidated_index is not None
                    else None,
                    "invalidated_index": bc.invalidated_index,
                    "failure_reason": bc.failure_reason,
                    "failure_audit": self._wave_audit_dict(bc.failure_audit),
                    "related_events": deepcopy(bc.related_events),
                    "status": bc.status,
                    "signal_index": bc.signal_index,
                    "reference_index": bc.reference_index,
                    "confirmed_index": bc.confirmed_index,
                    "direction": bc.direction,
                    "evidence": deepcopy(bc.evidence),
                    "intervals": {
                        key: self._fmt_dt(self.klines[int(value)].date)
                        for key, value in bc.evidence.items()
                        if key
                        in (
                            "a_start",
                            "a_end",
                            "b_start",
                            "b_end",
                            "c_start",
                            "c_end",
                            "reverse_pen_start",
                            "reverse_pen_end",
                            "reverse_pen_confirmed",
                            "a_dif_extreme_index",
                            "a_dea_extreme_index",
                            "c_dif_extreme_index",
                            "c_dea_extreme_index",
                            "reverse_pen_formed_index",
                            "reverse_pen_checked_index",
                            "replacement_signal_index",
                            "replacement_detected_index",
                            "original_a_start",
                            "original_a_end",
                        )
                    },
                    "msg": bc.msg,
                }
                for bc in self.bcs
            ],
        }


class ChanlunAnalyser:
    """缠论分析器。

    接收 easy_tdx K 线 DataFrame，执行缠论计算管道。

    用法：
        analyser = ChanlunAnalyser("SZ000001", "DAILY")
        analyser.process_klines(df)
        result = analyser.result
    """

    def __init__(
        self,
        code: str = "",
        frequency: str = "",
        config: ChanlunConfig | None = None,
    ) -> None:
        self._code = code
        self._frequency = frequency
        self._config = config or ChanlunConfig()
        self._result = ChanlunResult(
            code=code,
            frequency=frequency,
        )
        self._prev_df: pd.DataFrame | None = None

    @property
    def config(self) -> ChanlunConfig:
        return self._config

    @property
    def result(self) -> ChanlunResult:
        return self._result

    def process_klines(self, df: pd.DataFrame) -> ChanlunResult:
        """处理 K 线 DataFrame，执行缠论计算管道。

        Args:
            df: easy_tdx 返回的 K 线 DataFrame

        Returns:
            ChanlunResult 包含所有缠论计算结果

        Raises:
            ChanlunInputError: 时间缺失/重复/倒序或价格、成交量不合法。
                不自动跳行或重排，以免与外部图表和因子行号错位。
                失败时保留上次成功的结果；显式空输入仍清空结果。
        """
        # Build off-state: rejected input or a failed calculation must not destroy
        # the last valid snapshot or poison the base for the next incremental update.
        frame = prepare_frame(df)
        require_chronological(frame)
        result = ChanlunResult(code=self._result.code, frequency=self._result.frequency)
        # Step 1: DataFrame → Kline 列表
        klines = _df_to_klines(frame)
        result.klines = klines

        if not klines:
            self._prev_df, self._result = frame, result
            return result

        # Step 2: K线包含处理
        cklines = merge_klines(klines)
        result.cklines = cklines

        # Step 3: 分型识别
        fractals = find_fractals(cklines, self._config)
        result.fractals = fractals

        # Step 4: 笔计算
        bis = find_bis(fractals, self._config)
        result.bis = bis

        # Step 5: 中枢计算
        zss = find_zss(bis, self._config)
        result.zss = zss

        # Step 6: MACD 计算
        closes = [k.close for k in klines]
        result.macd = calc_macd(
            closes, self._config.macd_fast, self._config.macd_slow, self._config.macd_signal
        )

        # Step 7: 线段计算
        # The last pen may extend. Do not let it confirm a permanent segment.
        xds = find_xds([bi for bi in bis if bi.confirmed_index is not None], self._config)
        result.xds = xds
        result.unfinished_xd = find_unfinished_xd(bis, xds)
        result.structural_centres = find_structural_centres(xds)
        result.structural_signals = structure_signals(xds, klines, result.macd)

        # Step 8: 买卖点识别
        # One-class signals must share the exact structural divergence evidence.
        result.mmds, structural_bcs = to_chart_signals(result.structural_signals, xds)
        result.bcs = sorted(
            indicator_events(klines, result.macd, self._config, diagnostics=result.wave_diagnostics)
            + wave_events(klines, result.macd, diagnostics=result.wave_diagnostics)
            + wave_events(
                klines, result.macd, diagnostics=result.wave_diagnostics, family="nonstandard"
            )
            + special_wave_events(
                klines, result.macd, self.config, diagnostics=result.wave_diagnostics
            )
            + structural_bcs,
            key=lambda event: event.signal_index if event.signal_index is not None else -1,
        )

        link_wave_families(result.bcs, klines)
        self._prev_df, self._result = frame, result
        return result

    def append_klines(self, df_new: pd.DataFrame) -> ChanlunResult:
        """增量追加 K 线数据并重新计算。

        按交易时间合并新数据；同一时间以本次最后提供的整根 K 线为准，
        排序后在完整数据上重新执行缠论计算管道。支持历史补洞和修订。
        修订旧行情可能合理地改变历史结构，这不是历史数据版本回放。

        相比手动拼接 + process_klines 的优势：
        - API 更简洁，无需用户管理 DataFrame 拼接
        - 未来可优化为只重新计算受影响的部分

        Args:
            df_new: 新增的 K 线 DataFrame

        Returns:
            更新后的 ChanlunResult

        Raises:
            RuntimeError: 如果之前没有调用过 process_klines
            ChanlunInputError: 新数据不合法；上次成功结果保持不变。
        """
        if self._prev_df is None:
            msg = "请先调用 process_klines() 初始化，再使用 append_klines()"
            raise RuntimeError(msg)

        # Normalise each batch BEFORE deduplication (date aliases/string dates
        # represent the same timestamp). Corrections replace a whole candle.
        incoming = prepare_frame(df_new)
        combined = pd.concat([self._prev_df, incoming], ignore_index=True)
        if not combined.empty:
            combined = (
                combined.drop_duplicates(subset=["datetime"], keep="last")
                .sort_values("datetime", kind="stable")
                .reset_index(drop=True)
            )

        return self.process_klines(combined)

    def get_bis(self) -> list[BI]:
        return self._result.bis

    def get_zss(self) -> list[ZS]:
        return self._result.zss

    def get_fxs(self) -> list[FX]:
        return self._result.fractals

    def get_klines(self) -> list[Kline]:
        return self._result.klines

    def get_cklines(self) -> list[CLKline]:
        return self._result.cklines
