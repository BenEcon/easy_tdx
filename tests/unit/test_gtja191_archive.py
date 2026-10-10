"""Actual GTJA kernels through existing frozen research contracts, not test factors."""

import copy

import numpy as np
import pytest

from easy_tdx.factor.builtin.gtja191 import SPECS, GTJAFactor, GTJAPanelFactor
from easy_tdx.factor.data import qualify_factor_fields
from easy_tdx.web.factor_archive import validate_factor_archive
from easy_tdx.web.routers import research
from tests.unit.test_factor_archive import record
from tests.unit.test_factor_data import frozen

SERIES = [f"gtja191_{n:03}" for n, spec in sorted(SPECS.items()) if not spec.panel]


def envelope(result, mode):
    return {
        "format": "factor-research-v1",
        "mode": mode,
        "title": "GTJA 冻结验收（非投资建议）",
        "savedAt": "2026-10-10T10:00:00Z",
        "result": result,
    }


@pytest.mark.parametrize("name", SERIES)
def test_every_gtja_series_freezes_and_recomputes_without_live_data(monkeypatch, name):
    names = [name]
    need_vwap = "vwap" in SPECS[int(name[-3:])].inputs
    adjust = "NONE" if need_vwap else "QFQ"
    raw = frozen(f"0-000001-DAILY-{adjust}.json")
    frame = qualify_factor_fields(raw, frozen("0-000001-DAILY-NONE.json"), need_vwap=need_vwap)
    parameters = {name: {"window": 7} for name in names if SPECS[int(name[-3:])].window}
    for key in names:
        if SPECS[int(key[-3:])].windows:
            from tests.unit.test_gtja191_compound import custom
            from tests.unit.test_gtja191_conditional import DEFAULTS
            from tests.unit.test_gtja191_conditional import custom as conditional_custom

            number = int(key[-3:])
            if need_vwap:
                from tests.unit.test_gtja191_vwap import custom as vwap_custom

                parameters[key] = vwap_custom(number)
            else:
                parameters[key] = (
                    conditional_custom(number) if number in DEFAULTS else custom(number)
                )
    req = research.FactorComputeRequest(
        market="SZ",
        code="000001",
        count=160,
        adjust=adjust,
        factors=names,
        factor_parameters=parameters,
    )
    result = research._factor_result(req, frame).data
    assert not result["errors"]
    original = envelope(result, "series")
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(GTJAFactor, "compute", lambda *a: pytest.fail("read must not execute"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no live data"))
    newer = research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    assert newer["result"]["rows"] == result["rows"]
    assert newer["result"]["factor_definitions"] == result["factor_definitions"]
    assert original == before


@pytest.mark.asyncio
async def test_gtja_panel_and_series_joint_research_archive(monkeypatch):
    async def fetch(*args):
        # Explicit synthetic pool; price history varies by symbol and date.
        frame = frozen("0-000001-DAILY-NONE.json").copy()
        scale = np.exp(int(args[3][-1]) * 0.001 * np.arange(len(frame)))
        frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].mul(
            scale, axis=0
        )
        return frame

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    req = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
        factors=["gtja191_006", "gtja191_185", "gtja191_014"],
        factor_parameters={"gtja191_006": {"window": 7}},
        count=160,
        adjust="NONE",
    )
    result = (await research.factor_evaluate(req, None, None)).data
    assert not result["errors"]
    original = envelope(result, "evaluation")
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(GTJAPanelFactor, "compute_panel", lambda *a: pytest.fail("read executes"))
        guard.setattr(GTJAFactor, "compute", lambda *a: pytest.fail("read executes"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no live data"))
    newer = research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    assert newer["result"]["reports"] == result["reports"]
    assert newer["result"]["latest"] == result["latest"]
    assert len(newer["result"]["input_snapshots"]) == 6
    assert original == before


@pytest.mark.asyncio
async def test_recursive_series_and_panel_share_aligned_pool_without_state_leak(monkeypatch):
    async def fetch(*args):
        frame = frozen("0-000001-DAILY-NONE.json").copy()
        number = int(args[3][-1])
        price_scale = np.exp(number * 0.0005 * np.arange(len(frame)))
        frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].mul(
            price_scale, axis=0
        )
        frame["vol"] *= number + 1
        frame["amount"] *= price_scale * (number + 1)
        return frame

    monkeypatch.setattr(research, "fetch_adjusted_bars", fetch)
    monkeypatch.setattr(research, "closed_frame", lambda df: df)
    request = research.FactorEvaluationRequest(
        stocks=[{"market": "SZ", "code": f"00000{i}"} for i in range(1, 7)],
        factors=["gtja191_006", "gtja191_081", "gtja191_173"],
        count=160,
        adjust="NONE",
        factor_parameters={"gtja191_081": {"window": 7}, "gtja191_173": {"window": 7}},
    )
    result = (await research.factor_evaluate(request, None, None)).data
    assert not result["errors"]
    assert len(result["input_snapshots"]) == 6
    assert set(result["factor_definitions"]) == set(request.factors)
    original = envelope(result, "evaluation")
    before = copy.deepcopy(original)
    with monkeypatch.context() as guard:
        guard.setattr(GTJAFactor, "compute", lambda *a: pytest.fail("read executes"))
        guard.setattr(GTJAPanelFactor, "compute_panel", lambda *a: pytest.fail("read executes"))
        validate_factor_archive(original)
    monkeypatch.setattr(research, "fetch_adjusted_bars", lambda *a: pytest.fail("no live data"))
    newer = research.recompute_factor_payload(record(original))
    validate_factor_archive(newer)
    assert newer["result"]["reports"] == result["reports"]
    assert newer["result"]["latest"] == result["latest"]
    assert original == before
