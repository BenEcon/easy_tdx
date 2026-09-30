"""History summaries are opt-in delivery, never a different analysis."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.ownership_history import summarize_ownership_history
from tests.unit.test_chanlun_layered_ownership import PRICES
from tests.unit.test_chanlun_nested_ownership import nested_fixture
from tests.unit.test_chanlun_replay import ReplayRequest, snapshot
from tests.unit.test_chanlun_signal_levels import fixture

VIEWS = ('layered_movement_ownership', 'recursive_movement_ownership')


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('offset', [0, 37])
def test_current_detail_and_every_history_address_survive_projection(mirror, offset):
    items, bars, macd = nested_fixture(mirror, offset)
    obj = ChanlunResult(xds=items, klines=bars, macd=macd)
    full = obj.to_dict()
    summary = obj.to_dict(ownership_history='summary')
    assert {k: v for k, v in summary.items() if k not in VIEWS} == {
        k: v for k, v in full.items() if k not in VIEWS}
    for key in VIEWS:
        assert summary[key] == summarize_ownership_history(full[key])
        assert len(summary[key]['versions']) == len(full[key]['current_owner_ids'])
        assert [v['id'] for v in summary[key]['history_summaries']] == [
            v['id'] for v in full[key]['versions']]
        assert len(summary[key]['history_summaries']) > len(summary[key]['versions'])
    assert len(json.dumps(summary)) < len(json.dumps(full)) * .15
    history = full[VIEWS[1]]['versions']
    for version in (history[0], history[len(history)//2], history[-1]):
        # Recompute the original confirmed prefix, not a pruned future result.
        replay = ChanlunResult(xds=items, klines=bars[:version['known_index']+1], macd=macd)
        at_time = replay.to_dict(ownership_history='summary')[VIEWS[1]]
        assert version in at_time['versions']
        assert version['id'] in at_time['current_owner_ids']
    summary[VIEWS[1]]['versions'][0]['levels'].clear()
    summary[VIEWS[1]]['history_summaries'][0]['source_segment_indices'].clear()
    assert obj.to_dict() == full


def test_projection_keeps_separate_owners_and_has_no_mutable_aliases():
    versions = [{'id': name, 'known_index': i, 'source_segment_indices': [i],
                 'highest_completed_internal_level': 1, 'levels': [{'types': [name]}]}
                for i, name in enumerate(('old', 'left', 'right'))]
    original = {'versions': versions, 'current_owner_ids': ['left', 'right'],
                'external_m1_ids': ['outside'], 'natural_type_recursion_ready': False}
    saved = deepcopy(original)
    result = summarize_ownership_history(original)
    assert [v['id'] for v in result['versions']] == ['left', 'right']
    assert len(result['history_summaries']) == 3
    result['versions'][0]['source_segment_indices'].clear()
    assert result['history_summaries'][1]['source_segment_indices'] == [1]
    result['external_m1_ids'].clear()
    assert original == saved


def test_empty_summary_is_explicit_and_unknown_mode_is_rejected():
    obj = ChanlunResult()
    result = obj.to_dict(ownership_history='summary')
    for key in VIEWS:
        assert result[key]['history_format'] == 'summary_v1'
        assert result[key]['versions'] == result[key]['history_summaries'] == []
    with pytest.raises(ValueError, match='ownership_history'):
        obj.to_dict(ownership_history='truncate')
    assert all('history_format' not in obj.to_dict()[key] for key in VIEWS)


@pytest.mark.parametrize('route', ['analyze', 'industry', 'replay', 'replay/compare'])
@pytest.mark.parametrize('mode', ['full', 'summary'])
def test_http_routes_negotiate_mode_on_both_sides_of_comparison(monkeypatch, route, mode):
    from easy_tdx.chanlun import ChanlunAnalyser
    from easy_tdx.web.deps import get_client, get_mac_client_optional
    from easy_tdx.web.routers import chanlun

    items, bars, macd = fixture(PRICES, 10, 14)
    obj = ChanlunResult(xds=items, klines=bars, macd=macd)
    # Isolate transport/negotiation from market access. Algorithm equivalence
    # and historical timing are tested independently above.
    monkeypatch.setattr(ChanlunAnalyser, 'process_klines', lambda *_: obj)
    frame = pd.DataFrame(snapshot())
    monkeypatch.setattr(chanlun, 'fetch_adjusted_bars', AsyncMock(return_value=frame))
    monkeypatch.setattr(chanlun, 'stock_industries', AsyncMock(return_value=[
        {'board_code': '881155', 'market': 90}]))
    mac_client = SimpleNamespace(get_stock_kline=AsyncMock(return_value=frame))
    app = FastAPI()
    app.include_router(chanlun.router, prefix='/api/v1')
    app.dependency_overrides[get_client] = lambda: object()
    app.dependency_overrides[get_mac_client_optional] = lambda: mac_client
    client = TestClient(app)
    replay = ReplayRequest(code='000001', bars=snapshot(), visible_count=40).model_dump(mode='json')
    body = {
        'analyze': {'market': 'SZ', 'code': '000001'},
        'industry': {'stock_market': 'SZ', 'stock_code': '000001', 'board_code': '881155'},
        'replay': replay,
        'replay/compare': {'stock': replay, 'industry': {'code': '881155', 'bars': replay['bars']}},
    }[route]
    # Omitting the option must still produce the original, full response.
    url = f'/api/v1/chanlun/{route}'
    response = client.post(url + ('?ownership_history=summary' if mode == 'summary' else ''),
                           json=body)
    assert response.status_code == 200
    payload = response.json()
    results = ([payload['stock'], payload['industry']['result']] if route == 'replay/compare'
               else [payload['result']] if route == 'industry' else [payload])
    for result in results:
        assert result['released_movement_recursion'] == obj.to_dict(
            ownership_history=mode)['released_movement_recursion']
        for key in VIEWS:
            assert result[key] == obj.to_dict(ownership_history=mode)[key]
    assert client.post(url+'?ownership_history=invalid', json=body).status_code == 422
