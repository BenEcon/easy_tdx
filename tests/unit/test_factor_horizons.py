"""Independent horizon counts/returns, shared calculations and immutable replay."""

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from easy_tdx.computation import ComputationControl, ComputationStopped, computation_scope
from easy_tdx.factor import FACTORY_REGISTRY
from easy_tdx.factor.horizons import normalize_horizons
from easy_tdx.factor.research import cross_section_report
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.research_archive import ArchiveError
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import frozen
from tests.unit.test_factor_validation import TemporalScore


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


def run(pool, **kwargs):
    return cross_section_report(pool, [TemporalScore.name], 5, 3, horizons=[1, 5, 10, 20], **kwargs)


@pytest.mark.parametrize("preprocess", ["raw", "mad_zscore"])
@pytest.mark.parametrize("mode", ["full", "holdout", "expanding", "rolling"])
def test_each_horizon_matches_single_window_without_recomputing_factor(
    pool, monkeypatch, preprocess, mode
):
    dates = next(iter(pool.values())).datetime
    split = (
        None
        if mode == "full"
        else (
            {
                "mode": "holdout",
                "train_end": str(dates.iloc[39].date()),
                "validation_end": str(dates.iloc[69].date()),
            }
            if mode == "holdout"
            else {
                "mode": "walk_forward",
                "training": mode,
                "train_bars": 40,
                "validation_bars": 25,
                "test_bars": 25,
            }
        )
    )
    original = TemporalScore.compute
    calls = []

    def count(self, frame):
        calls.append(len(frame))
        return original(self, frame)

    monkeypatch.setattr(TemporalScore, "compute", count)
    result = run(pool, preprocess=preprocess, validation=split)
    assert len(calls) == len(pool)  # not 4 * assets
    assert result["settings"]["horizons"] == [1, 5, 10, 20]
    for item in result["horizon_comparison"]["results"]:
        h = item["horizon"]
        report = item["reports"][0]
        assert report["observations"] == 107 - 2 - h
        assert report["rank_ic_mean"] == pytest.approx(1)
        assert report["coverage"] == 105 / 107
        # Six fixed ascending factors, independently known 2 assets per layer.
        expected = [np.mean([(1 + i / 1000) ** h - 1 for i in (j, j + 1)]) for j in (1, 3, 5)]
        assert report["layer_means"] == pytest.approx(expected)
        assert report["daily"][-h]["label_end"] is None
        assert all(d["n"] == 0 for d in report["daily"][-h:])
        single = cross_section_report(
            pool, [TemporalScore.name], h, 3, preprocess, validation=split
        )
        assert item["reports"] == single["reports"]
        assert item["validation"] == single["validation"]
        if split:
            assert item["validation"]["folds"][0]["phases"][0]["purged_dates"] == h
            assert (
                item["validation"]["folds"][0]["phases"][0]["reports"][0]["observations"] == 38 - h
            )
    assert result["reports"] == result["horizon_comparison"]["results"][1]["reports"]


@pytest.mark.parametrize(
    "bad", [[], [1, 1], [5, 7], [1, 10], [True, 5], [5.0], ["5"], "5", [1, 5, 10, 20, 60]]
)
def test_invalid_horizons_fail_before_computation(pool, monkeypatch, bad):
    def forbidden(*args):
        pytest.fail("invalid selection must not compute")

    monkeypatch.setattr(TemporalScore, "compute", forbidden)
    with pytest.raises(ValueError):
        cross_section_report(pool, [TemporalScore.name], 5, 3, horizons=bad)
    with pytest.raises(ValidationError):
        research.FactorEvaluationRequest(
            stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 6)],
            factors=["momentum_20d"],
            horizons=bad,
        )


def test_order_is_canonical_and_legacy_none_is_not_expanded(pool):
    a = run(pool)
    b = cross_section_report(pool, [TemporalScore.name], 5, 3, horizons=[20, 10, 5, 1])
    assert a == b
    c = cross_section_report(pool, [TemporalScore.name], 5, 3)
    assert c["settings"]["horizons"] is None and c["horizon_comparison"] is None
    assert a["input_fingerprint"] != c["input_fingerprint"]
    assert a["reports"] == c["reports"]
    assert normalize_horizons(5, [20, 5]) == [5, 20]


def test_missing_bar_invalidates_the_entire_span_for_each_horizon(pool):
    missing_day = next(iter(pool.values())).datetime.iloc[70].strftime("%Y-%m-%d")
    for symbol in list(pool)[:3]:
        pool[symbol] = pool[symbol].drop(index=70)
    result = run(pool)
    for item in result["horizon_comparison"]["results"]:
        h = item["horizon"]
        rows = item["reports"][0]["daily"]
        pos = next(i for i, row in enumerate(rows) if row["date"] == missing_day)
        assert all(r["n"] == 3 and r["rank_ic"] is None for r in rows[pos - h : pos + 1])
        assert rows[pos - h - 1]["n"] == 6
        assert rows[pos + 1]["n"] == 6


def test_longest_horizon_cannot_silently_shrink_validation_or_calendar(pool):
    with pytest.raises(ValueError, match="长于远期窗口"):
        run(
            pool,
            validation={
                "mode": "walk_forward",
                "training": "expanding",
                "train_bars": 40,
                "validation_bars": 20,
                "test_bars": 20,
            },
        )
    long = {
        k: pd.concat([f, f.iloc[:1].assign(datetime=pd.Timestamp("2040-01-01"))])
        for k, f in pool.items()
    }
    # Added future rows don't change completed earlier labels at ANY horizon.
    a, b = run(pool), run(long)
    for old, new in zip(a["horizon_comparison"]["results"], b["horizon_comparison"]["results"]):
        h = old["horizon"]
        assert old["reports"][0]["daily"][:-h] == new["reports"][0]["daily"][: 107 - h]
    expanded = {
        k: pd.DataFrame(
            {"datetime": pd.date_range("2020-01-01", periods=801), "open": 1.0, "close": 2.0}
        )
        for k in pool
    }
    with pytest.raises(ValueError, match="超过 800"):
        run(expanded)


async def frozen_payload(monkeypatch):
    calls = []

    async def fetch(_c, _m, market, code, *_args):
        calls.append((market, code))
        f = frozen("0-000001-DAILY-NONE.json").copy()
        scale = np.exp((int(code) + 1) * 0.0001 * np.arange(len(f)))
        f[["open", "high", "low", "close"]] = f[["open", "high", "low", "close"]].mul(scale, axis=0)
        f.attrs["snapshot_metadata"]["qa_note"] = (
            "合成验收：冻结000001加时变倍率，不是其他标的真实行情"
        )
        return f

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda f: f)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 6)],
        factors=["momentum_20d"],
        count=160,
        adjust="NONE",
        horizons=[1, 5, 10, 20],
        validation={
            "mode": "walk_forward",
            "training": "expanding",
            "train_bars": 80,
            "validation_bars": 30,
            "test_bars": 30,
        },
    )
    data = (await research.factor_evaluate(req, None, None)).data
    assert len(calls) == 5
    return {
        "format": "factor-research-v1",
        "mode": "evaluation",
        "title": "多远期合成验收",
        "savedAt": "2026-10-10T12:00:00Z",
        "result": data,
    }


@pytest.mark.asyncio
async def test_route_fetches_once_and_archive_replay_retains_all_horizons(monkeypatch):
    payload = await frozen_payload(monkeypatch)
    before = copy.deepcopy(payload)
    validate_factor_archive(payload)

    async def forbidden(*args):
        pytest.fail("frozen replay must not fetch live data")

    monkeypatch.setattr(research, "fetch_adjusted_bars", forbidden)
    replay = research.recompute_factor_payload(record(payload))
    assert replay["result"]["horizon_comparison"] == payload["result"]["horizon_comparison"]
    assert replay["result"]["settings"]["horizons"] == [1, 5, 10, 20]
    assert payload == before
    for mode in ["drop", "duplicate", "primary", "end", "value", "purge"]:
        # JSON serialization separates the intentionally shared primary result.
        bad = json.loads(json.dumps(payload))
        items = bad["result"]["horizon_comparison"]["results"]
        if mode == "drop":
            items.pop()
        if mode == "duplicate":
            items[0]["horizon"] = 5
        if mode == "primary":
            items[1]["reports"][0]["rank_ic_mean"] = -0.333
        if mode == "end":
            items[0]["reports"][0]["daily"][0]["label_end"] = "2000-01-01"
        if mode == "value":
            items[2]["reports"][0]["daily"][0]["ic"] = float("inf")
        if mode == "purge":
            items[3]["validation"]["test_reports"][0]["daily"][-1]["ic"] = 0.9
        with pytest.raises(ArchiveError):
            validate_factor_archive(bad)


def test_existing_temporal_archive_migrates_only_to_single_horizon():
    source = json.loads(Path("tests/fixtures/factor_archive/time-validation.json").read_text())
    assert "horizons" not in source["result"]["settings"]
    original = copy.deepcopy(source)
    newer = research.recompute_factor_payload(record(source))
    assert newer["result"]["settings"]["horizons"] is None
    assert newer["result"]["horizon_comparison"] is None
    assert newer["result"]["validation"] == source["result"]["validation"]
    assert (
        newer["recomputed_from"]["horizon_migration"]
        == "legacy_single_horizon_to_explicit_horizons_none"
    )
    assert source == original


def test_cancellation_between_horizons_never_returns_partial_success(pool, monkeypatch):
    from easy_tdx.factor import research as core

    original = core.daily_report
    control = ComputationControl()
    calls = []

    def cancel_after_first(*args):
        rows = original(*args)
        calls.append(args[-2])
        control.request()
        return rows

    monkeypatch.setattr(core, "daily_report", cancel_after_first)
    with pytest.raises(ComputationStopped), computation_scope(control):
        run(pool)
    assert calls == [1]


def test_failed_factor_is_reported_once_without_fabricated_horizon_values(pool, monkeypatch):
    def fail(*args):
        raise ValueError("明确缺少输入")

    monkeypatch.setattr(TemporalScore, "compute", fail)
    result = run(pool)
    assert result["errors"] == {TemporalScore.name: "明确缺少输入"}
    assert all(not r["reports"] for r in result["horizon_comparison"]["results"])
