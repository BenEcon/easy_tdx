"""Instrument routing must not confuse SH000001 with SZ000001 equity."""

from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_tdx.mac.enums import Adjust, BoardType, Period
from easy_tdx.models.enums import Market
from easy_tdx.web.routers.bars import router
from easy_tdx.web.routers.chanlun_replay import ReplayRequest, replay_snapshot


@pytest.fixture
def service():
    standard, mac = AsyncMock(), AsyncMock()
    frame = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2025-01-06") + pd.Timedelta(days=i),
                "open": 10 + i,
                "high": 12 + i,
                "low": 9 + i,
                "close": 11 + i,
                "vol": 100,
                "amount": 1000,
            }
            for i in range(35)
        ]
    )
    standard.get_index_bars.return_value = frame
    mac.get_stock_kline.return_value = frame
    mac.get_board_list.return_value = pd.DataFrame(
        [{"code": "881155", "market": 90, "name": "银行"}]
    )
    app = FastAPI()
    app.include_router(router)
    app.state.tdx_client = standard
    app.state.mac_client = mac
    with TestClient(app) as client:
        yield client, standard, mac, app


@pytest.mark.parametrize("market,code", [("SH", "000001"), ("SZ", "399001"), ("SZ", "399006")])
def test_index_uses_explicit_market_and_dedicated_command(service, market, code):
    client, standard, mac, app = service
    app.state.mac_client = None
    response = client.get(
        "/bars/research", params={"kind": "index", "market": market, "code": code}
    )
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["metadata"]["actual_adjust"] == "NONE"
    assert snapshot["metadata"]["source"] == "TDX_INDEX"
    assert snapshot["metadata"]["instrument"]["market"] == market
    assert "is_closed" in snapshot["data"][0]
    assert standard.get_index_bars.call_args.args[:2] == (Market[market], code)
    standard.get_security_bars.assert_not_called()
    mac.get_stock_kline.assert_not_called()
    req = ReplayRequest(code=f"index:{market}:{code}", bars=snapshot["data"], visible_count=35)
    result = replay_snapshot(req, ownership_history="summary")
    assert result["code"] == f"index:{market}:{code}"
    assert result["kline_count"] == 35


@pytest.mark.parametrize("board_type", ["HY", "HY2", "GN", "FG", "DQ"])
def test_board_uses_catalog_market_and_no_adjustment(service, board_type):
    client, standard, mac, _ = service
    response = client.get(
        "/bars/research", params={"kind": "board", "code": "881155", "board_type": board_type}
    )
    assert response.status_code == 200
    meta = response.json()["metadata"]
    assert meta["instrument"] == {
        "kind": "board",
        "market": "90",
        "code": "881155",
        "board_type": board_type,
        "name": "银行",
    }
    assert meta["actual_adjust"] == meta["requested_adjust"] == "NONE"
    assert mac.get_board_list.call_args.kwargs["board_type"] == BoardType[board_type]
    assert mac.get_stock_kline.call_args.args[:2] == (90, "881155")
    assert mac.get_stock_kline.call_args.kwargs["adjust"] == Adjust.NONE
    standard.get_security_bars.assert_not_called()
    standard.get_index_bars.assert_not_called()


def test_missing_board_no_fallback_to_equity(service):
    client, standard, mac, app = service
    assert client.get("/bars/research?kind=board&code=000001").status_code == 404
    mac.get_stock_kline.assert_not_called()
    app.state.mac_client = None
    assert client.get("/bars/research?kind=board&code=881155").status_code == 503
    standard.get_security_bars.assert_not_called()


def test_120_minute_is_never_silently_replaced(service):
    client, standard, mac, _ = service
    response = client.get("/bars/research?kind=index&market=SH&code=000001&category=MIN_120")
    assert response.status_code == 422
    standard.get_index_bars.assert_not_called()
    assert client.get("/bars/research?kind=board&code=881155&category=MIN_120").status_code == 200
    assert mac.get_stock_kline.call_args.args[2:] == (Period.MINS, 0, 600, 24)


@pytest.mark.parametrize(
    "params",
    [
        "kind=stock&code=000001",
        "kind=index&code=1",
        "kind=index&code=000001&market=BJ",
        "kind=board&code=881155&board_type=unknown",
        "kind=index&code=000001&count=801",
    ],
)
def test_invalid_requests(service, params):
    assert service[0].get("/bars/research?" + params).status_code == 422


def test_empty_index_is_explicit_error(service):
    client, standard, _, app = service
    app.state.mac_client = None
    standard.get_index_bars.return_value = pd.DataFrame()
    assert client.get("/bars/research?kind=index&code=000001").status_code == 404


@pytest.mark.parametrize("market,code", [("SH", "000001"), ("SZ", "399001")])
def test_mac_index_explicit_market_no_equity_heuristic(service, market, code):
    client, standard, mac, _ = service
    snapshot = client.get(
        "/bars/research", params={"kind": "index", "market": market, "code": code}
    ).json()
    assert snapshot["metadata"]["source"] == "MAC_INDEX"
    assert snapshot["metadata"]["actual_adjust"] == "NONE"
    assert mac.get_stock_kline.call_args.args[:2] == (int(Market[market]), code)
    assert mac.get_stock_kline.call_args.kwargs["adjust"] == Adjust.NONE
    standard.get_security_bars.assert_not_called()
    standard.get_index_bars.assert_not_called()


def test_empty_mac_index_falls_back_to_explicit_index_command(service):
    client, standard, mac, _ = service
    mac.get_stock_kline.return_value = pd.DataFrame()
    snapshot = client.get("/bars/research?kind=index&market=SH&code=000001").json()
    assert snapshot["metadata"]["source"] == "TDX_INDEX"
    assert standard.get_index_bars.call_args.args[:2] == (Market.SH, "000001")
    standard.get_security_bars.assert_not_called()


def test_research_excludes_unfinished_bar_and_later_rows(service, monkeypatch):
    from easy_tdx.web.routers import chanlun_observations as research

    data = service[0].get("/bars/research?kind=index&code=000001").json()["data"]
    for bar in data:
        bar["datetime"] = bar.get("datetime", bar.get("date"))
    data[10]["is_closed"] = False
    lengths = []

    def observe(frame, category, **kwargs):
        lengths.append(len(frame))
        return {"category": category, "last_date": str(frame.datetime.iloc[-1]), "divergences": []}

    monkeypatch.setattr(research, "observe", observe)
    result = research.observations(
        research.StudyRequest(
            as_of="2025-12-31",
            series=[
                {"code": "index:SH:000001", "category": "DAY", "bars": data},
            ],
        )
    )
    assert lengths == [10]
    assert result["rows"][0]["excluded_bars"] == 25
