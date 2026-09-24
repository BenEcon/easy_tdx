"""Replay computes prefixes, never hides future-derived structures after analysis."""
from copy import deepcopy

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from easy_tdx.chanlun import ChanlunAnalyser
from easy_tdx.web.routers.chanlun_replay import ReplayRequest, replay_snapshot


def snapshot(size=80):
    return [dict(datetime=pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
                 open=20 + (i % 16 if i % 32 < 16 else 16 - i % 16),
                 close=20 + (i % 16 if i % 32 < 16 else 16 - i % 16),
                 high=21 + (i % 16 if i % 32 < 16 else 16 - i % 16),
                 low=19 + (i % 16 if i % 32 < 16 else 16 - i % 16), vol=100)
            for i in range(size)]


@pytest.mark.parametrize("cutoff", [1, 2, 20, 41, 79, 80])
def test_replay_equals_independent_prefix(cutoff):
    rows = snapshot()
    request = ReplayRequest(code="SH600699", bars=rows, visible_count=cutoff)
    actual = replay_snapshot(request)
    assert actual.pop("replay")["historical_data_vintage"] is False
    expected = ChanlunAnalyser(code="SH600699", frequency="day").process_klines(
        pd.DataFrame(rows[:cutoff])).to_dict()
    assert actual == expected


def test_unseen_future_changes_cannot_change_replay():
    rows = snapshot()
    before = replay_snapshot(ReplayRequest(code="test", bars=rows, visible_count=41))
    changed = deepcopy(rows)
    for bar in changed[41:]:
        for column in ("open", "close", "high", "low"):
            bar[column] *= 100
    after = replay_snapshot(ReplayRequest(code="test", bars=changed, visible_count=41))
    assert before == after


@pytest.mark.parametrize("case", ["duplicate", "unsorted", "nan", "ohlc", "count", "limit"])
def test_invalid_snapshot_is_rejected(case):
    rows = snapshot()
    count = 20
    if case == "duplicate":
        rows[1]["datetime"] = rows[0]["datetime"]
    elif case == "unsorted":
        rows.reverse()
    elif case == "nan":
        rows[0]["close"] = float("nan")
    elif case == "ohlc":
        rows[0]["high"] = 0
    elif case == "count":
        count = len(rows) + 1
    elif case == "limit":
        rows = snapshot(801)
    with pytest.raises(ValidationError):
        ReplayRequest(code="test", bars=rows, visible_count=count)


def test_empty_reanalysis_clears_previous_structures():
    analyser = ChanlunAnalyser(code="test", frequency="daily")
    previous = analyser.process_klines(pd.DataFrame(snapshot()))
    assert previous.bis
    empty = analyser.process_klines(pd.DataFrame())
    assert empty.to_dict()["bi_count"] == 0
    assert not empty.macd and not empty.structural_centres and not empty.bcs
    assert empty.code == "test"
    assert previous.bis  # previously returned snapshots must remain unchanged


def test_replay_route_registration_and_validation():
    from easy_tdx.web.routers.chanlun import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    body = ReplayRequest(code="test", bars=snapshot(), visible_count=20).model_dump(mode="json")
    response = client.post("/api/v1/chanlun/replay", json=body)
    assert response.status_code == 200
    assert response.json()["kline_count"] == 20
    body["visible_count"] = 81
    assert client.post("/api/v1/chanlun/replay", json=body).status_code == 422
