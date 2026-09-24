"""Common-time replay with missing dates and different stock/industry lengths."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from easy_tdx.web.routers.chanlun_replay import (
    ComparisonReplayRequest,
    ReplayRequest,
    replay_comparison,
    replay_snapshot,
    router,
)


def candles(offsets, *, minutes=False):
    return [dict(datetime=datetime(2026, 1, 1, 9, 30) + (
        timedelta(minutes=i) if minutes else timedelta(days=i)),
        open=10, high=12, low=9, close=11, vol=100, amount=1100) for i in offsets]


def request(stock_days, industry_days, count, category="DAY"):
    minutes = category.startswith("MIN_")
    return ComparisonReplayRequest(
        stock=dict(code="SH600699", category=category,
                   bars=candles(stock_days, minutes=minutes), visible_count=count),
        industry=dict(code="881155", bars=candles(industry_days, minutes=minutes)),
    )


def test_alignment_uses_time_not_row_count():
    req = request([0, 3, 4], [0, 1, 2, 3, 4, 5], 2)
    data = replay_comparison(req)
    assert data["stock"]["kline_count"] == 2
    assert data["industry"]["result"]["kline_count"] == 4
    assert len(data["industry"]["bars"]) == 4
    assert data["industry"]["bars"][-1]["amount"] == 1100
    assert data["alignment"]["status"] == "aligned"
    assert data["industry"]["result"] == replay_snapshot(ReplayRequest(
        code=req.industry.code, bars=req.industry.bars, visible_count=4))


@pytest.mark.parametrize("category", ["DAY", "MIN_5"])
def test_missing_industry_dates_are_not_filled(category):
    data = replay_comparison(request([0, 5, 10], [0, 10, 15], 2, category))
    assert data["alignment"]["status"] == "earlier"
    assert data["alignment"]["industry_as_of"] < data["alignment"]["as_of"]
    assert len(data["industry"]["bars"]) == 1
    assert data["industry"]["result"]["frequency"] == (
        "5min" if category == "MIN_5" else "day")


def test_history_before_industry_snapshot_is_explicitly_unavailable():
    data = replay_comparison(request([0, 1, 2], [2, 3, 4], 1))
    assert data["industry"] is None
    assert data["alignment"]["industry_as_of"] is None
    assert data["alignment"]["status"] == "unavailable"


def test_latest_stock_still_truncates_more_recent_industry():
    data = replay_comparison(request([0, 1, 2], [0, 1, 2, 3, 4], 3))
    assert len(data["industry"]["bars"]) == 3
    assert data["industry"]["result"]["replay"]["visible_count"] == 3


def test_industry_future_prices_do_not_change_past_results():
    req = request([0, 1, 2], [0, 1, 2, 3, 4], 2)
    before = replay_comparison(req)
    changed = deepcopy(req)
    for bar in changed.industry.bars[2:]:
        bar.open *= 100
        bar.high *= 100
        bar.low *= 100
        bar.close *= 100
    assert replay_comparison(changed) == before


def test_industry_snapshot_must_also_be_chronological():
    with pytest.raises(ValidationError):
        request([0, 1, 2], [0, 2, 1], 2)


def test_comparison_http_contract():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    response = TestClient(app).post("/api/v1/chanlun/replay/compare", json=
                                   request([0, 3, 4], [0, 1, 2, 3, 4], 2).model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["alignment"]["status"] == "aligned"
