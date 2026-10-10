"""No-C markers retain the original causal dual-line event, mirrored for tops."""

from copy import deepcopy

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.divergence_signals import _pivot_candidates, indicator_events
from tests.unit.test_october_second_divergence import reverse_pen_sample


@pytest.mark.parametrize("top", [False, True])
def test_special_is_one_original_event_and_waits_for_reverse_pen(top):
    bars, macd = reverse_pen_sample(top)
    ordinary = indicator_events(bars, macd)
    # Opposite colour at the price extreme; no change to any price/DIF/DEA.
    macd["hist"][9] = -0.2 if top else 0.2
    for n in range(10, 20):
        (event,) = indicator_events(bars[:n], {k: v[:n] for k, v in macd.items()})
        assert event.bc_type.value == "macd"
        assert event.evidence["special_no_c"] == 1
        assert event.evidence["signal_hist"] == macd["hist"][9]
        assert event.reference_index == 1 and event.signal_index == 9
        assert event.status == ("confirmed" if n >= 15 else "candidate")
        assert event.confirmed_index == (14 if n >= 15 else None)
    for field in ("price", "previous_price", "dif", "previous_dif", "dea", "previous_dea"):
        assert event.evidence[field] == ordinary[0].evidence[field]
    (payload,) = ChanlunResult(klines=bars, bcs=[event]).to_dict()["bcs"]
    assert payload["type"] == "macd" and payload["evidence"]["special_no_c"] == 1
    assert payload["curr_date"] == "2026-01-10"
    assert payload["confirmed_date"] == "2026-01-15"
    assert payload["intervals"]["reverse_pen_confirmed"] == "2026-01-15"
    assert "c_area" not in payload["evidence"]


@pytest.mark.parametrize("top", [False, True])
@pytest.mark.parametrize("hist", [0, float("nan"), float("inf"), -0.1])
def test_zero_nonfinite_and_normal_colour_are_not_special(top, hist):
    bars, macd = reverse_pen_sample(top)
    macd["hist"][9] = -hist if top else hist
    (event,) = _pivot_candidates(bars, macd)
    assert "special_no_c" not in event.evidence


@pytest.mark.parametrize("top", [False, True])
@pytest.mark.parametrize("failure", ["dif", "dea", "price"])
def test_special_has_the_same_invalidation_and_frozen_history(top, failure):
    bars, macd = reverse_pen_sample(top)
    macd["hist"][9] = -0.2 if top else 0.2
    (confirmed,) = indicator_events(bars, macd)
    broken = deepcopy(bars)
    changed = deepcopy(macd)
    if failure == "price":
        if top:
            broken[13].high = bars[9].high + 1
        else:
            broken[13].low = bars[9].low - 1
    else:
        changed[failure][13] = changed[failure][1]
    event = next(e for e in indicator_events(broken, changed) if e.signal_index == 9)
    assert event.status == "superseded" and event.confirmed_index is None
    assert event.invalidated_index == 13 and event.evidence["special_no_c"] == 1
    assert indicator_events(bars, macd)[0] == confirmed


def test_603936_green_bar_high_does_not_skip_nearest_pivot_for_older_high():
    # Frozen 60-minute QFQ values, Sep 21 10:30 through Sep 22 11:30.
    from datetime import datetime, timedelta

    from easy_tdx.chanlun.types import Kline

    highs = [21.86, 21.90, 21.62, 21.71, 22.68, 23.76]
    dif = [0.434052568, 0.404690445, 0.368299098, 0.345162935, 0.378145456, 0.472269693]
    dea = [0.641547330, 0.594175953, 0.549000582, 0.508233052, 0.482215533, 0.480226365]
    bars = [
        Kline(i, datetime(2026, 9, 21) + timedelta(hours=i), h - 0.1, h - 0.1, h, h - 0.5, 100)
        for i, h in enumerate(highs)
    ]
    macd = {"dif": dif, "dea": dea, "hist": [2 * (d - e) for d, e in zip(dif, dea)]}
    events = indicator_events(bars, macd)
    (event,) = events
    assert event.signal_index == 4 and event.reference_index == 1
    assert event.evidence["special_no_c"] == 1
    assert event.status == "superseded" and event.invalidated_index == 5
    assert not any(e.signal_index == 5 for e in events)  # DIF at 23.76 worsened.
