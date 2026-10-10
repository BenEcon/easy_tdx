"""DEA tolerance stays an isolated diagnostic; strict events never change."""

from copy import deepcopy
from dataclasses import asdict

import pytest

from easy_tdx.chanlun.divergence_signals import _dea_tolerance_check, wave_events
from tests.unit.test_wave_rule_comparison import sample


@pytest.mark.parametrize("top", [False, True])
@pytest.mark.parametrize(
    "c,expected",
    [(99, True), (100, True), (105, True), (105.000001, False), (0, False), (-1, False)],
)
def test_exact_tolerance_boundary_and_axis(top, c, expected):
    sign = 1 if top else -1
    check = {
        "gate": "dea_extreme_and_zero_axis",
        "passed": 0 < c < 100,
        "values": {
            "a_extreme": sign * 100,
            "c_extreme": sign * c,
            "direction": "up" if top else "down",
        },
    }
    before = deepcopy(check)
    result = _dea_tolerance_check(check)
    assert result["passed"] == expected
    assert check == before
    assert result["values"]["tolerance_ratio"] == 0.05


@pytest.mark.parametrize(
    "a,c,passed",
    [
        (0, 0, False),
        (1e-10, 1e-10, False),
        (1e-9, 1.01e-9, False),
        (1e-9, 0.9e-9, True),
        (1e-8, 1.04e-8, True),
    ],
)
def test_near_zero_has_no_absolute_allowance(a, c, passed):
    result = _dea_tolerance_check(
        {"passed": 0 < c < a, "values": {"a_extreme": a, "c_extreme": c, "direction": "up"}}
    )
    assert result["passed"] == passed
    assert result["values"]["tolerance_enabled"] == (a > 1e-9)


@pytest.mark.parametrize("top", [False, True])
def test_prefix_checks_closed_status_and_strict_events_unchanged(top):
    bars, macd = sample(top)
    sign = 1 if top else -1
    macd["dea"][5:7] = [sign * 1.85, sign * 1.86]  # 3.33% worse than A=1.8
    for count in (6, 7, 8, 9):
        ks = bars[:count]
        values = {k: v[:count] for k, v in macd.items()}
        strict = wave_events(ks, values)
        audit = []
        observed = wave_events(ks, values, diagnostics=audit)
        assert [asdict(e) for e in observed] == [asdict(e) for e in strict] == []
        report = next(r for r in audit if r["c_start"] == 5)
        assert report["status"] == "blocked"
        comparison = next(c for c in report["comparisons"] if c["mode"] == "dea_tolerance")
        assert comparison["mode"] == "dea_tolerance" and comparison["passed"]
        assert comparison["closed"] == (count >= 8)
        assert comparison["known_index"] == min(count - 1, 7)
        assert all(
            not c["passed"]
            for c in report["comparisons"]
            if c["mode"] in ("full_a", "equal_price", "full_a_equal_price")
        )
        gate = next(g for g in comparison["checks"] if g["gate"] == "dea_extreme_tolerance")
        assert not gate["values"]["strict_passed"]
        assert gate["values"]["c_extreme_index"] == (5 if count == 6 else 6)


@pytest.mark.parametrize("failure", ["dif", "area", "price", "axis", "pullback", "missing"])
def test_other_gates_never_relaxed(failure):
    bars, macd = sample()
    macd["dea"][5:7] = [-1.85, -1.86]
    if failure == "dif":
        macd["dif"][6] = -2.1
    elif failure == "area":
        macd["hist"][6] = -4
    elif failure == "price":
        bars[5].low = bars[6].low = 20
    elif failure == "axis":
        macd["dea"][3] = 0
    elif failure == "pullback":
        macd["dea"][2:5] = [-1.8, -1.8, -1.8]
    else:
        macd["dea"][3] = float("nan")
    audit = []
    wave_events(bars, macd, diagnostics=audit)
    report = next(r for r in audit if r["c_start"] == 5)
    comparison = next(c for c in report["comparisons"] if c["mode"] == "dea_tolerance")
    assert not comparison["passed"]


def test_later_dea_can_break_research_without_retroactive_confirmation():
    bars, macd = sample()
    macd["dea"][5:7] = [-1.85, -2]
    first = []
    wave_events(bars[:6], {k: v[:6] for k, v in macd.items()}, diagnostics=first)
    report = next(r for r in first if r["c_start"] == 5)
    pending = next(c for c in report["comparisons"] if c["mode"] == "dea_tolerance")
    assert pending["passed"] and not pending["closed"]
    final = []
    assert not wave_events(bars, macd, diagnostics=final)
    report = next(r for r in final if r["c_start"] == 5)
    closed = next(c for c in report["comparisons"] if c["mode"] == "dea_tolerance")
    assert closed["closed"] and not closed["passed"]
