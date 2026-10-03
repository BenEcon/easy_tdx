"""Top signals must obey the same causal contract as mirrored bottom signals."""
from datetime import datetime, timedelta

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.divergence_signals import indicator_events, segment_evidence, wave_events
from easy_tdx.chanlun.types import Kline


def candles(highs):
    return [Kline(i, datetime(2026, 1, 1) + timedelta(days=i), h - .5, h - .5,
                  h, h - 1, 100) for i, h in enumerate(highs)]


def mirror(bars, macd):
    return ([Kline(b.index, b.date, 100 - b.open, 100 - b.close,
                   100 - b.low, 100 - b.high, b.amount) for b in bars],
            {key: [-v for v in values] for key, values in macd.items()})


def top_fixture():
    return candles([20, 22, 21, 23, 22, 24, 25, 24]), {
        'dif': [2, 2, 1.9, 1.5, 1.4, 1.3, 1.2, 1.1],
        'dea': [1.8, 1.8, 1.7, 1.4, 1.3, 1.2, 1.1, 1],
        'hist': [-.1] * 8,
    }


def test_top_new_high_supersession_and_exact_price_date():
    bars, macd = top_fixture()
    events = indicator_events(bars, macd)
    assert [(e.signal_index, e.reference_index, e.confirmed_index, e.status) for e in events] == [
        (3, 1, None, 'superseded'), (5, 3, None, 'superseded'), (6, 3, None, 'candidate')]
    assert all(e.direction == 'up' and '非缠论一卖' in e.msg for e in events)
    payload = ChanlunResult(klines=bars, bcs=events).to_dict()['bcs']
    assert payload[-1]['curr_date'] == '2026-01-07'
    assert payload[-1]['confirmed_date'] is None  # no completed reverse pen
    assert payload[-1]['prev_date'] == '2026-01-04'


@pytest.mark.parametrize('change', ['equal_high', 'lower_high', 'dif_equal', 'dea_equal',
                                   'dif_higher', 'dea_higher', 'dif_zero', 'dea_negative'])
def test_top_rejects_missing_price_or_dual_line_condition(change):
    bars, macd = top_fixture()
    bars, macd = bars[:5], {key: value[:5] for key, value in macd.items()}
    if change in ('equal_high', 'lower_high'):
        bars[3].high = 22 if change == 'equal_high' else 21.5
    else:
        line, condition = change.split('_')
        macd[line][3] = {'equal': macd[line][1], 'higher': macd[line][1] + .1,
                        'zero': 0, 'negative': -.1}[condition]
    assert not indicator_events(bars, macd)


def wave_fixture():
    return candles([20, 21, 25, 23, 22, 26, 25.5, 24]), {
        'dif': [-.1, 2, 2, 1, .5, 1.5, 1.4, 1.3],
        'dea': [-.1, 1.8, 1.7, 1.2, .9, 1.3, 1.2, 1.1],
        'hist': [-.2, 2, 1, -.3, -.2, .5, .2, -.1],
    }


def test_top_wave_red_area_and_confirmation_after_price_high():
    bars, macd = wave_fixture()
    event, = wave_events(bars, macd)
    assert (event.direction, event.signal_index, event.detected_index,
            event.confirmed_index) == ('up', 5, 5, 7)
    assert event.evidence['area_ratio'] == pytest.approx(.7 / 3)
    assert event.evidence['a_dif_extreme'] == 2
    assert event.evidence['c_dif_extreme'] == 1.5
    assert '红柱面积' in event.msg and '峰值降低' in event.msg


def test_top_wave_candidate_invalidates_when_red_area_later_grows():
    bars, macd = wave_fixture()
    before = wave_events(bars[:7], {k: v[:7] for k, v in macd.items()})
    assert before[0].status == 'candidate'
    bars[7].high = 27
    macd['hist'][7] = 4
    after = wave_events(bars, macd)
    assert len(after) == 1
    assert after[0].status == 'superseded'
    assert after[0].confirmed_index is None


def test_confirmed_top_wave_does_not_change_with_later_bars():
    bars, macd = wave_fixture()
    confirmed, = wave_events(bars, macd)
    bars.extend(candles([23, 27, 24]))
    for i, bar in enumerate(bars):
        bar.index = i
    for key, values in {'dif': [1.2, 1.1, 1], 'dea': [1, .9, .8],
                        'hist': [-.2, .1, -.1]}.items():
        macd[key].extend(values)
    for count in range(8, len(bars) + 1):
        events = wave_events(bars[:count], {k: v[:count] for k, v in macd.items()})
        assert events[0] == confirmed


@pytest.mark.parametrize('change', ['no_high', 'area_grows', 'dif_peak_grows', 'dea_peak_grows'])
def test_top_wave_rejects_non_divergent_segments(change):
    bars, macd = wave_fixture()
    if change == 'no_high':
        bars[5].high = bars[6].high = 25
    elif change == 'area_grows':
        macd['hist'][5] = 4
    else:
        macd[change.split('_')[0]][5] = 3
    assert segment_evidence(bars, macd, (1, 2), (5, 6), 'up') is None
    assert not wave_events(bars, macd)


@pytest.mark.parametrize('factory, detector', [(top_fixture, indicator_events), (wave_fixture, wave_events)])
def test_all_prefixes_are_exact_top_bottom_mirrors(factory, detector):
    bars, macd = factory()
    bottom_bars, bottom_macd = mirror(bars, macd)
    for count in range(1, len(bars) + 1):
        tops = detector(bars[:count], {k: v[:count] for k, v in macd.items()})
        bottoms = detector(bottom_bars[:count], {k: v[:count] for k, v in bottom_macd.items()})
        assert len(tops) == len(bottoms)
        for top, bottom in zip(tops, bottoms):
            assert top.direction == 'up' and bottom.direction == 'down'
            for field in ('signal_index', 'reference_index', 'detected_index', 'confirmed_index', 'status'):
                assert getattr(top, field) == getattr(bottom, field)
            if top.confirmed_index is not None:
                assert top.confirmed_index > top.signal_index
            for key, value in top.evidence.items():
                other = bottom.evidence[key]
                if key in ('price', 'previous_price', 'nearest_pivot_price'):
                    assert value + other == pytest.approx(100)
                elif 'dif' in key or 'dea' in key:
                    assert value == pytest.approx(-other)
                else:
                    assert value == pytest.approx(other)
