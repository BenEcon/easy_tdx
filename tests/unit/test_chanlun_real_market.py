"""Frozen vendor OHLC acceptance, not synthetic segment or historical-vintage data."""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from easy_tdx.chanlun.analyser import ChanlunAnalyser

FIXTURE = Path(__file__).parents[1] / 'fixtures/chanlun/600699-qfq-20260929.json'


@pytest.fixture(scope='module')
def market():
    return json.loads(FIXTURE.read_text())


def analyse(market, through='2026-09-29'):
    bars = [b for b in market['bars'] if b['datetime'][:10] <= through]
    result = ChanlunAnalyser(code='600699', frequency='day').process_klines(pd.DataFrame(bars))
    return result, result.to_dict(ownership_history='summary')


def test_data_provenance_and_precision(market):
    assert market['adjust'] == 'QFQ'
    assert market['historical_data_vintage'] is False
    assert market['macd'] == [12, 26, 9]
    raw = json.dumps(market['bars'], ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    assert hashlib.sha256(raw.encode()).hexdigest() == market['bars_sha256']
    assert len(market['bars']) == 800
    expected = {'2026-06-29': 20.49, '2026-07-09': 20.58, '2026-07-14': 19.71,
                '2026-07-20': 19.21, '2026-07-24': 19.18}
    for bar in market['bars']:
        if bar['datetime'][:10] in expected:
            assert bar['low'] == pytest.approx(expected[bar['datetime'][:10]], abs=1e-5)


@pytest.mark.parametrize('through,day,kind,status,confirmation', [
    ('2026-07-09', '2026-07-09', 'macd', None, None),
    ('2026-07-14', '2026-07-14', 'macd', None, None),
    ('2026-07-14', '2026-07-14', 'macd_wave', None, None),
    ('2026-07-15', '2026-07-14', 'macd_wave', 'confirmed', '2026-07-15'),
    ('2026-07-20', '2026-07-20', 'macd', 'candidate', None),
    ('2026-07-21', '2026-07-20', 'macd', 'confirmed', '2026-07-21'),
    ('2026-07-24', '2026-07-24', 'macd', 'candidate', None),
    ('2026-07-27', '2026-07-24', 'macd', 'superseded', None),
    ('2026-07-27', '2026-07-27', 'macd', 'candidate', None),
    ('2026-07-28', '2026-07-27', 'macd', 'confirmed', '2026-07-28'),
])
def test_real_prefix_event_lifecycle(market, through, day, kind, status, confirmation):
    _, data = analyse(market, through)
    events = [e for e in data['bcs'] if e['type'] == kind and e['curr_date'] == day]
    if status is None:
        assert not events
    else:
        assert len(events) == 1
        assert events[0]['status'] == status
        assert events[0]['confirmed_date'] == confirmation
    # A MACD-only observation must not silently become a structure-gated first buy.
    assert not [e for e in data['mmds'] if str(e.get('date', '')).startswith('2026-07')]


def test_real_structure_and_macd_baseline(market):
    result, data = analyse(market)
    assert (data['bi_count'], data['xd_count'], data['zs_count']) == (52, 6, 10)
    assert result.macd['dif'][745] > result.macd['dif'][734]
    assert result.macd['dea'][745] < result.macd['dea'][734]
    wave = next(e for e in data['bcs'] if e['type'] == 'macd_wave'
                and e['curr_date'] == '2026-07-14')
    assert wave['intervals'] == {
        'a_start': '2026-05-28', 'a_end': '2026-07-02',
        'b_start': '2026-07-03', 'b_end': '2026-07-10',
        'c_start': '2026-07-13', 'c_end': '2026-07-14',
    }
    assert wave['evidence']['area_ratio'] == pytest.approx(0.004261023807099702)
    recursion = data['released_movement_recursion']
    assert recursion['accepted_segment_count'] == 6
    assert recursion['highest_completed_level'] == 0
    assert recursion['unresolved_segment_indices'] == list(range(6))
    assert recursion['eligible_for_trading'] is False
    # The real sample is a negative higher-level acceptance, not an M2/M3 proof.
    assert not recursion['external_frontier_ids']
