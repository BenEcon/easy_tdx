"""Full real-engine results survive immutable archives, account isolation and backups."""

import copy
import json
import uuid

import pytest

from easy_tdx.web.backtest_schemas import BacktestRequest
from easy_tdx.web.research_archive import ArchiveError, ResearchArchive, encode_archive
from easy_tdx.web.routers.backtest import _ohlcv_to_df, _run_backtest
from tests.unit.test_radar_archive import radar_payload
from tests.unit.test_research_archive_api import app_client as archive_app_client
from tests.unit.test_research_archive_api import login

app_client = archive_app_client


def backtest_payload():
    chart = radar_payload()
    bars = chart["charts"][0]["bars"]
    request = {
        "symbol": "SZ:300450",
        "category": "DAY",
        "adjust": "QFQ",
        "strategy": "ma_cross",
        "params": {"fast": 7, "slow": 31},
        "cash": 1000000.25,
        "commission": 0.0003,
        "min_commission": 5.25,
        "stamp_tax": 0.001,
        "slippage": 0.0002,
        "execution": "next_open",
        "start_date": bars[0]["datetime"][:10],
        "end_date": bars[-1]["datetime"][:10],
        "ohlcv": bars,
    }
    frame = _ohlcv_to_df(bars, category="DAY", adjust="QFQ")
    result = json.loads(json.dumps(_run_backtest(frame, BacktestRequest(**request))))
    return {
        "format": "backtest-research-v1",
        "title": "先导智能原回测",
        "savedAt": "2026-10-10T04:00:00Z",
        "request": request,
        "metadata": chart["charts"][0]["metadata"],
        "result": result,
        "radarSource": chart["radarSource"],
    }


@pytest.fixture(scope="module")
def original():
    return backtest_payload()


def test_actual_result_cookie_roundtrip_and_all_owner_boundaries(app_client, original):
    client, _, sessions, _, _ = app_client
    login(client, sessions)
    key = str(uuid.uuid4())
    url = f"/api/v1/research/archives/{key}"
    response = client.put(url, json={"kind": "backtest", "payload": original, "name": "原回测"})
    assert response.status_code == 201, response.text
    assert len(original["result"]["trades"]) > 0
    assert client.get(url).json()["payload"] == original
    assert client.get(url).json()["kind"] == "backtest"
    for username in ("Bob", "Admin"):
        login(client, sessions, username)
        assert client.get(url).status_code == 404
    login(client, sessions)
    assert (
        client.post(url + "/actions", json={"revision": 1, "action": "delete"}).status_code == 200
    )
    assert (
        client.post(url + "/actions", json={"revision": 2, "action": "restore"}).status_code == 200
    )
    assert client.get(url).json()["payload"] == original


@pytest.mark.parametrize(
    "path,value",
    [
        (("request", "cash"), True),
        (("request", "params"), []),
        (("request", "symbol"), "SZ:300750"),
        (("request", "commission"), None),
        (("request", "execution"), ["next_open"]),
        (("metadata", "actual_adjust"), "HFQ"),
        (("result", "performance", "sharpe"), "3.5"),
        (("result", "equity_curve"), []),
        (("result", "equity_curve", 0, "datetime"), "2000-01-01 15:00:00"),
        (("result", "trades", 0, "rejected"), "false"),
        (("result", "trades", 0, "datetime"), "2000-01-01 15:00:00"),
        (("result", "positions"), [None]),
        (("request", "ohlcv", 0, "close"), float("inf")),
    ],
)
def test_invalid_archive_rejected_before_write(tmp_path, original, path, value):
    payload = copy.deepcopy(original)
    node = payload
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    store = ResearchArchive(tmp_path / "archive.db")
    with pytest.raises(ArchiveError) as failure:
        store.create("alice", str(uuid.uuid4()), "backtest", payload, "invalid")
    assert failure.value.status == 422
    assert store.list("alice")["items"] == []


def test_backup_restore_supports_full_backtest(tmp_path, original):
    from easy_tdx.web.account_store import AccountStore
    from easy_tdx.web.research_backup import create_backup, restore_backup

    root = tmp_path / "source"
    root.mkdir()
    account = AccountStore(root / "accounts.db").create_user(
        "alice", "Test-only-password!", role="admin"
    )
    key = str(uuid.uuid4())
    ResearchArchive(root / "research_archives.db").create(
        account.id, key, "backtest", original, "原档"
    )
    create_backup(root, tmp_path / "backup")
    restore_backup(tmp_path / "backup", tmp_path / "restored")
    assert (
        ResearchArchive(tmp_path / "restored/research_archives.db").get(account.id, key)["payload"]
        == original
    )


def test_nullable_metrics_and_unknown_original_fields_preserved(original):
    payload = copy.deepcopy(original)
    payload["result"]["performance"]["sharpe"] = None
    payload["result"]["future_field"] = {"精度": 0.0000000123456789}
    encoded, _ = encode_archive("backtest", payload, 25 * 1024 * 1024)
    assert json.loads(encoded) == payload
