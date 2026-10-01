"""Oct 1 user-confirmed nearest local swing and whole-leg zero-axis rules."""
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.divergence_signals import indicator_events, segment_evidence, wave_events
from easy_tdx.chanlun.types import Kline


def fixture(lows, dif, dea):
    return ([Kline(i, datetime(2026, 9, 28) + timedelta(minutes=5*i), p+.5, p+.5,
                   p+1, p, 100) for i, p in enumerate(lows)],
            {'dif': dif, 'dea': dea, 'hist': [-.1]*len(lows)})


def mirror(bars, macd):
    return ([Kline(b.index, b.date, 100-b.open, 100-b.close, 100-b.low, 100-b.high, 100)
             for b in bars], {k: [-v for v in values] for k, values in macd.items()})


@pytest.mark.parametrize('top', [False, True])
def test_nearest_swing_replaces_older_more_extreme_reference(top):
    # At index 5, both lines improve against old low 20 but not the nearest low 21.
    bars, macd = fixture([23, 20, 23, 21, 23, 20.5, 23],
                        [-3, -3, -2, -1, -1, -2, -1],
                        [-2.8, -2.8, -1.8, -.8, -.8, -1.8, -.8])
    if top:
        bars, macd = mirror(bars, macd)
    assert not indicator_events(bars, macd)
    # A new adjacent extreme can qualify even without breaking the old all-time extreme.
    macd['dif'][5] = .7 if top else -.7
    macd['dea'][5] = .6 if top else -.6
    event, = indicator_events(bars, macd)
    assert (event.signal_index, event.reference_index, event.confirmed_index) == (5, 3, 6)


def test_document_no_new_low_and_both_lines_required():
    bars, macd = fixture([3150, 3125.20, 3150, 3135.26, 3150],
                        [-3, -3, -2, -1, -1], [-2.8, -2.8, -2, -.8, -.8])
    assert not indicator_events(bars, macd)
    # Synthetic 35.00 -> 35.37 case: DIF decreases, DEA increases, hence no top.
    bars, macd = fixture([66, 65, 66, 64.63, 66],
                        [-2, -2, -1.8, -1.5, -1], [-1.5, -1.5, -1.3, -1.6, -1])
    bars, macd = mirror(bars, macd)
    assert not indicator_events(bars, macd)


@pytest.mark.parametrize('top', [False, True])
@pytest.mark.parametrize('line', ['dif', 'dea'])
@pytest.mark.parametrize('index', [1, 5])
@pytest.mark.parametrize('value', [0, .1])
def test_whole_wave_cross_or_touch_zero_is_excluded(top, line, index, value):
    bars, macd = fixture([25, 24, 20, 22, 23, 19, 19.5, 21],
                        [.1, -2, -2, -1, -.5, -1.5, -1.4, -1.3],
                        [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1])
    macd['hist'] = [.2, -2, -1, .3, .2, -.5, -.2, .1]
    macd[line][index] = value
    if top:
        bars, macd = mirror(bars, macd)
    audit = []
    assert segment_evidence(bars, macd, (1, 2), (5, 6), 'up' if top else 'down', audit=audit, whole_leg_axis=True) is None
    assert any(g['gate'] == f'{line}_whole_leg_zero_axis' and not g['passed'] for g in audit)
    assert not wave_events(bars, macd)


def test_wave_cannot_bypass_nearest_pivot_condition():
    bars, macd = fixture([25, 24, 20, 22, 18, 23, 19, 19.5, 21],
                        [.1, -2, -2, -1, -.5, -.5, -1.5, -1.4, -1.3],
                        [.1, -1.8, -1.7, -1.2, -.9, -.9, -1.3, -1.2, -1.1])
    macd['hist'] = [.2, -2, -1, .3, .2, .1, -.5, -.2, .1]
    assert segment_evidence(bars, macd, (1, 2), (6, 7), 'down') is not None
    assert not wave_events(bars, macd)  # 19 does not break the more recent low 18.
