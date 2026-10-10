"""Temporal boundaries, independent expected counts and archive compatibility."""

import copy

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.factor import FACTORY_REGISTRY, Factor
from easy_tdx.factor.research import cross_section_report
from easy_tdx.factor.validation import PURGE_REASON, normalize_validation, validation_plan
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.research_archive import ArchiveError
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import frozen


class TemporalScore(Factor):
    name = "qa_temporal"
    category = "technical"
    description = "synthetic temporal acceptance"
    inputs = ("open",)

    def compute(self, frame):
        return frame["open"].rolling(3).mean()


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setitem(FACTORY_REGISTRY, TemporalScore.name, TemporalScore)
    return {
        f"SZ:{i:06d}": pd.DataFrame(
            {
                "datetime": pd.date_range("2025-01-01", periods=107, freq="B"),
                "open": float(i),
                "close": 100 * (1 + i / 1000) ** np.arange(107),
            }
        )
        for i in range(1, 7)
    }


def config(pool):
    dates = next(iter(pool.values())).datetime
    return {
        "mode": "holdout",
        "train_end": str(dates.iloc[39].date()),
        "validation_end": str(dates.iloc[69].date()),
    }


def report(pool, validation, preprocess="raw"):
    return cross_section_report(pool, [TemporalScore.name], 5, 3, preprocess, validation=validation)


@pytest.mark.parametrize("horizon", [-5, 0, True, 5.0, "5", None])
def test_core_rejects_invalid_forward_horizon_before_computation(pool, horizon):
    with pytest.raises(ValueError, match="远期窗口必须为正整数"):
        cross_section_report(pool, [TemporalScore.name], horizon, 3)


@pytest.mark.parametrize("groups", [0, 1, 7, True, 3.0, "3", None])
def test_core_rejects_invalid_group_count_before_computation(pool, groups):
    with pytest.raises(ValueError, match="分层数必须为整数"):
        cross_section_report(pool, [TemporalScore.name], 5, groups)


def test_core_never_silently_treats_unknown_preprocessing_as_raw(pool):
    with pytest.raises(ValueError, match="未知预处理方式"):
        cross_section_report(pool, [TemporalScore.name], 5, 3, "unknown")


@pytest.mark.parametrize("preprocess", ["raw", "mad_zscore"])
def test_holdout_hand_counts_purges_and_no_warmup_restart(pool, preprocess):
    result = report(pool, config(pool), preprocess)
    value = result["validation"]
    train, valid, test = value["folds"][0]["phases"]
    assert [p["date_count"] for p in (train, valid, test)] == [40, 30, 37]
    assert [p["purged_dates"] for p in (train, valid, test)] == [5, 5, 5]
    # Two missing feature warmup days only at input start, not each phase start.
    assert [p["reports"][0]["observations"] for p in (train, valid, test)] == [33, 25, 32]
    assert all(p["reports"][0]["rank_ic_mean"] == pytest.approx(1) for p in (train, valid, test))
    assert train["reports"][0]["coverage"] == 38 / 40
    assert valid["reports"][0]["coverage"] == 1
    rows = value["test_reports"][0]["daily"]
    assert all(r["rank_ic"] is None and r["reason"] == PURGE_REASON for r in rows[-5:])
    assert all(r["rolling_rank_ic"] is None for r in rows[:19])
    assert rows[19]["rolling_rank_ic"] == pytest.approx(1)
    assert rows[-1]["layer_spread"] is None
    assert result["reports"][0]["observations"] == 100  # full sample not overwritten
    assert result["settings"]["validation"] == config(pool)


@pytest.mark.parametrize("preprocess", ["raw", "mad_zscore"])
def test_later_prices_cannot_leak_into_earlier_phase_statistics(pool, preprocess):
    original = report(pool, config(pool), preprocess)
    changed = copy.deepcopy(pool)
    for i, frame in enumerate(changed.values(), 1):
        frame.loc[40:, "close"] *= 1 + (7 - i) / 10
        frame.loc[40:, "open"] *= 10 - i
    altered = report(changed, config(pool), preprocess)
    assert (
        original["validation"]["folds"][0]["phases"][0]
        == altered["validation"]["folds"][0]["phases"][0]
    )
    # Countercheck: unpurged full-sample observations really did see this mutation.
    assert original["reports"][0]["daily"][35]["ic"] != altered["reports"][0]["daily"][35]["ic"]
    assert original["input_fingerprint"] != altered["input_fingerprint"]


@pytest.mark.parametrize("training", ["expanding", "rolling"])
def test_walk_forward_nonoverlap_and_partial_tail_is_not_dropped(pool, training):
    cfg = {
        "mode": "walk_forward",
        "training": training,
        "train_bars": 40,
        "validation_bars": 20,
        "test_bars": 20,
    }
    value = report(pool, cfg)["validation"]
    assert len(value["folds"]) == 3
    assert [f["phases"][0]["date_count"] for f in value["folds"]] == (
        [40, 60, 80] if training == "expanding" else [40, 40, 40]
    )
    assert [f["phases"][2]["date_count"] for f in value["folds"]] == [20, 20, 7]
    assert value["folds"][-1]["phases"][2]["partial"] is True
    r = value["test_reports"][0]
    assert len(r["daily"]) == 47 and r["observations"] == 15 + 15 + 2
    assert len({d["date"] for d in r["daily"]}) == 47
    assert [d["date"] for d in r["daily"]] == next(iter(pool.values())).datetime.iloc[
        60:
    ].dt.strftime("%Y-%m-%d").tolist()
    assert all(d["rolling_rank_ic"] is None for d in r["daily"])  # purged fold tails reset rolling
    assert r["diagnostics"][PURGE_REASON] == 15


def test_too_short_partial_tail_is_explicitly_empty_not_success(pool):
    shortened = {k: v.iloc[:102] for k, v in pool.items()}
    cfg = {
        "mode": "walk_forward",
        "training": "rolling",
        "train_bars": 40,
        "validation_bars": 20,
        "test_bars": 20,
    }
    phase = report(shortened, cfg)["validation"]["folds"][-1]["phases"][-1]
    assert phase["date_count"] == 2 and phase["partial"]
    assert phase["label_eligible_dates"] == 0 and phase["reports"][0]["observations"] == 0
    assert phase["reports"][0]["rank_ic_mean"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "holdout", "train_end": "2025-02-30", "validation_end": "2025-04-01"},
        {"mode": "holdout", "train_end": "2025-04-01", "validation_end": "2025-02-01"},
        {
            "mode": "holdout",
            "train_end": "2025-02-01",
            "validation_end": "2025-04-01",
            "unknown": 1,
        },
        {
            "mode": "walk_forward",
            "training": "rolling",
            "train_bars": 40.0,
            "validation_bars": 20,
            "test_bars": 20,
        },
        {
            "mode": "walk_forward",
            "training": "rolling",
            "train_bars": True,
            "validation_bars": 20,
            "test_bars": 20,
        },
        {
            "mode": "walk_forward",
            "training": "shuffle",
            "train_bars": 40,
            "validation_bars": 20,
            "test_bars": 20,
        },
    ],
)
def test_invalid_settings_fail_not_coerce(bad):
    with pytest.raises(ValidationError):
        normalize_validation(bad)


def test_out_of_range_dates_insufficient_bars_and_unknown_api_fields_fail(pool):
    with pytest.raises(ValueError, match="合并观测日 801"):
        validation_plan(pd.date_range("2020-01-01", periods=801), 5, config(pool))
    with pytest.raises(ValueError, match="实际行情日期"):
        report(pool, {"mode": "holdout", "train_end": "2030-01-01", "validation_end": "2031-01-01"})
    with pytest.raises(ValueError, match="未缩短配置"):
        report(
            pool,
            {
                "mode": "walk_forward",
                "training": "rolling",
                "train_bars": 100,
                "validation_bars": 20,
                "test_bars": 20,
            },
        )
    with pytest.raises(ValidationError):
        research.FactorEvaluationRequest(
            stocks=[{"market": "SZ", "code": f"{i:06d}"} for i in range(6)],
            factors=[TemporalScore.name],
            unexpected_split=True,
        )


def test_split_changes_fingerprint_not_full_sample_values(pool):
    plain = report(pool, None)
    split = report(pool, config(pool))
    assert plain["reports"] == split["reports"]
    assert plain["input_fingerprint"] != split["input_fingerprint"]
    assert plain["validation"] is None


def test_missing_internal_bar_and_insufficient_assets_remain_excluded(pool):
    for key in list(pool)[:2]:
        pool[key] = pool[key].drop(index=80)
    r = report(pool, config(pool))["validation"]["test_reports"][0]
    affected = [d for d in r["daily"] if "2025-04-16" <= d["date"] <= "2025-04-23"]
    # Independent index positions: labels at 75..80 span the absent bar 80.
    assert len(affected) == 6 and all(d["n"] == 4 and d["rank_ic"] is None for d in affected)
    assert r["observations"] == 32 - 6


@pytest.mark.parametrize("horizon", [1, 5, 10, 20])
def test_each_supported_horizon_purges_its_own_label_span(pool, horizon):
    result = cross_section_report(pool, [TemporalScore.name], horizon, 5, validation=config(pool))
    phases = result["validation"]["folds"][0]["phases"]
    assert [p["purged_dates"] for p in phases] == [horizon] * 3
    assert [p["reports"][0]["observations"] for p in phases] == [
        38 - horizon,
        30 - horizon,
        37 - horizon,
    ]


def test_adding_future_rows_does_not_change_finished_rolling_folds(pool):
    cfg = {
        "mode": "walk_forward",
        "training": "expanding",
        "train_bars": 40,
        "validation_bars": 20,
        "test_bars": 20,
    }
    first = report({k: f.iloc[:100] for k, f in pool.items()}, cfg)["validation"]
    later = report(pool, cfg)["validation"]
    assert first["folds"] == later["folds"][:2]
    a, b = first["test_reports"][0]["daily"], later["test_reports"][0]["daily"]
    # In completed folds only, label endpoint availability in boundary-purged
    # rows can become known later; it must not make those rows valid retroactively.
    assert [{k: v for k, v in row.items() if k != "label_end"} for row in a] == [
        {k: v for k, v in row.items() if k != "label_end"} for row in b[:40]
    ]


@pytest.mark.asyncio
async def test_route_archive_read_and_replay_preserve_exact_split(monkeypatch):
    async def fetch(*args):
        return frozen("0-000001-DAILY-NONE.json").copy()

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 6)],
        factors=["momentum_20d"],
        count=160,
        adjust="NONE",
        validation={
            "mode": "walk_forward",
            "training": "expanding",
            "train_bars": 80,
            "validation_bars": 30,
            "test_bars": 30,
        },
    )
    data = (await research.factor_evaluate(req, None, None)).data
    payload = {
        "format": "factor-research-v1",
        "mode": "evaluation",
        "title": "时间划分验收",
        "savedAt": "2026-10-10T12:00:00Z",
        "result": data,
    }
    original = copy.deepcopy(payload)
    validate_factor_archive(payload)
    new = research.recompute_factor_payload(record(payload))
    assert new["result"]["validation"] == data["validation"]
    assert new["result"]["settings"]["validation"] == data["settings"]["validation"]
    assert new["result"]["settings"]["factor_parameters"] == {"momentum_20d": {"window": 20}}
    assert payload == original
    for corruption in ("missing", "overlap", "purge", "config"):
        bad = copy.deepcopy(payload)
        v = bad["result"]["validation"]
        if corruption == "missing":
            v["folds"].pop()
        if corruption == "overlap":
            v["test_reports"][0]["daily"][0]["date"] = "2000-01-01"
        if corruption == "purge":
            v["test_reports"][0]["daily"][-1]["ic"] = 0.5
        if corruption == "config":
            v["config"]["train_bars"] = 90
        with pytest.raises(ArchiveError):
            validate_factor_archive(bad)
    # A known historical full-sample schema may migrate only to explicit None.
    old = copy.deepcopy(payload)
    old["result"]["settings"].pop("validation")
    old["result"].pop("validation")
    replay = research.recompute_factor_payload(record(old))
    assert replay["result"]["validation"] is None
    assert (
        replay["recomputed_from"]["configuration_migration"]
        == "legacy_full_sample_to_explicit_validation_none"
    )
