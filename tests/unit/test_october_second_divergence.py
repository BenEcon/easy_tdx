"""Oct 2 indicator-only rules; structural evidence keeps its independent scope."""
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.divergence_signals import indicator_events, segment_evidence, wave_events
from easy_tdx.chanlun.types import Kline
from easy_tdx.chanlun.analyser import ChanlunResult


def sample(top=False):
    lows = [25, 24, 20, 22, 23, 19, 19.5, 21]
    bars = [Kline(i, datetime(2026, 1, 1) + timedelta(days=i), p+.5, p+.5,
                  p+1, p, 100) for i, p in enumerate(lows)]
    macd = {'dif': [.1, -2, -2, -1, -.5, -1.5, -1.4, -1.3],
            'dea': [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1],
            'hist': [.2, -2, -1, .3, .2, -.5, -.2, .1]}
    if top:
        bars = [Kline(b.index, b.date, 100-b.open, 100-b.close,
                      100-b.low, 100-b.high, b.amount) for b in bars]
        macd = {k: [-v for v in values] for k, values in macd.items()}
    return bars, macd


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('line', ['dif', 'dea'])
@pytest.mark.parametrize('index', [3, 4])
@pytest.mark.parametrize('value', [0, .1])
def test_middle_b_touch_or_cross_rejects_wave_but_not_structural_evidence(top, line, index, value):
    bars, macd = sample(top)
    macd[line][index] = -value if top else value
    direction = 'up' if top else 'down'
    audit = []
    assert segment_evidence(bars, macd, (1, 2), (5, 6), direction) is not None
    assert segment_evidence(bars, macd, (1, 2), (5, 6), direction,
                            whole_leg_axis=True) is not None  # prior scope alone
    assert segment_evidence(bars, macd, (1, 2), (5, 6), direction,
                            whole_abc_axis=True, audit=audit) is None
    assert any(g['gate'] == f'{line}_whole_abc_zero_axis' and not g['passed'] for g in audit)
    assert not wave_events(bars, macd)


@pytest.mark.parametrize('top', [False, True])
def test_same_side_abc_remains_eligible(top):
    bars, macd = sample(top)
    event, = wave_events(bars, macd)
    assert event.status == 'confirmed'
    assert event.signal_index == 5
    assert event.confirmed_index == 7


@pytest.mark.parametrize('top', [False, True])
def test_two_shrinking_bars_are_preliminary_not_final_and_can_fail(top):
    bars, macd = sample(top)
    sign = -1 if top else 1
    for i in range(8, 10):
        bars.append(Kline(i, datetime(2026, 1, 1) + timedelta(days=i), bars[7].open,
                          bars[7].close, bars[7].high, bars[7].low, 100))
    macd['dif'] += [-1.2 * sign, -1.1 * sign]
    macd['dea'] += [-1.0 * sign, -.9 * sign]
    macd['hist'][5:] = [v * sign for v in [-.5, -.3, -.1, -4, .1]]
    early, = wave_events(bars[:6], {k: v[:6] for k, v in macd.items()})
    assert (early.detected_index, early.preliminary_index, early.confirmed_index) == (5, None, None)
    preliminary, = wave_events(bars[:8], {k: v[:8] for k, v in macd.items()})
    assert preliminary.status == 'candidate'
    assert preliminary.preliminary_index == 7
    assert preliminary.confirmed_index is None
    invalid, = wave_events(bars, macd)
    assert invalid.status == 'superseded'
    assert invalid.invalidated_index == 8
    assert invalid.confirmed_index is None
    assert invalid.preliminary_index == 7  # retain the audit trail, not a solid marker
    payload, = ChanlunResult(klines=bars, bcs=[invalid]).to_dict()['bcs']
    assert payload['preliminary_date'] == '2026-01-08'
    assert payload['invalidated_date'] == '2026-01-09'


@pytest.mark.parametrize('top', [False, True])
def test_a_single_bar_c_prompts_on_that_bar_and_confirms_only_later(top):
    bars, macd = sample(top)
    macd['hist'][6] = -.1 if top else .1
    early, = wave_events(bars[:6], {k: v[:6] for k, v in macd.items()})
    assert early.status == 'candidate' and early.detected_index == 5
    complete, = wave_events(bars[:7], {k: v[:7] for k, v in macd.items()})
    assert complete.confirmed_index == 6
    assert complete.signal_index == 5


def test_zero_histogram_does_not_close_c_or_finalize():
    bars, macd = sample()
    macd['hist'][7] = 0
    event, = wave_events(bars, macd)
    assert event.status == 'candidate'
    assert event.confirmed_index is None
    assert event.preliminary_index == 7


def reverse_pen_sample(top=False):
    prices = [12, 10, 11, 12, 13, 14, 13, 12, 11, 9, 10, 11, 12, 13, 12, 11, 10, 9.5, 10]
    bars = [Kline(i, datetime(2026, 1, 1) + timedelta(days=i), p+.4, p+.6,
                  p+1, p, 100) for i, p in enumerate(prices)]
    macd = {'dif': [-3]*9 + [-1.5]*10, 'dea': [-2.5]*9 + [-1.2]*10,
            'hist': [-1]*9 + [-.6, -.4, -.2] + [.1]*7}
    if top:
        bars = [Kline(b.index, b.date, 100-b.open, 100-b.close,
                      100-b.low, 100-b.high, b.amount) for b in bars]
        macd = {k: [-v for v in values] for k, values in macd.items()}
    return bars, macd


@pytest.mark.parametrize('top', [False, True])
def test_dual_line_finality_waits_for_exact_extreme_reverse_pen_on_every_prefix(top):
    bars, macd = reverse_pen_sample(top)
    for n in range(10, 20):
        event, = indicator_events(bars[:n], {k: v[:n] for k, v in macd.items()})
        assert event.signal_index == 9 and event.reference_index == 1
        assert event.preliminary_index == (11 if n >= 12 else None)
        assert event.confirmed_index == (14 if n >= 15 else None)
        assert event.status == ('confirmed' if n >= 15 else 'candidate')
    assert event.evidence['reverse_pen_start'] == 9
    assert event.evidence['reverse_pen_end'] == 13
    payload, = ChanlunResult(klines=bars, bcs=[event]).to_dict()['bcs']
    assert payload['curr_date'] == '2026-01-10'
    assert payload['confirmed_date'] == '2026-01-15'
    assert payload['intervals']['reverse_pen_confirmed'] == '2026-01-15'


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('line', ['dif', 'dea'])
def test_dual_line_can_fail_after_preliminary_but_before_reverse_pen(top, line):
    bars, macd = reverse_pen_sample(top)
    macd[line][13] = macd[line][1]  # Equality before first reverse pen breaks improvement.
    event, = indicator_events(bars, macd)
    assert event.status == 'superseded' and event.preliminary_index == 11
    assert event.invalidated_index == 13 and event.confirmed_index is None
    assert 'DIF 或 DEA' in event.failure_reason


def test_confirmed_dual_line_history_is_not_rewritten_by_a_later_move():
    bars, macd = reverse_pen_sample()
    original, = indicator_events(bars, macd)
    bars.append(Kline(19, datetime(2026, 1, 20), 8.4, 8.6, 9, 8, 100))
    for key, value in [('dif', -4), ('dea', -3), ('hist', -2)]:
        macd[key].append(value)
    assert indicator_events(bars, macd)[0] == original
