"""Archived scan lineage is standalone, exact, owner-bound, and never rerun."""

import copy
import uuid

import pytest

from easy_tdx.web import scan_evidence
from easy_tdx.web.research_archive import ArchiveError, ResearchArchive, _archive_time
from tests.market_matrix import entries
from tests.unit.test_research_archive import payload
from tests.unit.test_research_archive_api import app_client as archive_app_client
from tests.unit.test_research_archive_api import login
from tests.unit.test_scan_evidence import frozen

app_client = archive_app_client


def radar_payload(entry_id="300450-qfq-20261002"):
    value, result = frozen(entry_id)
    receipt = scan_evidence.evidence_row(value, result, 0)
    receipt.update(task_id="a" * 32, storage="memory", current_execution_version="new-version")
    row = receipt["row"]
    review = {
        "symbol": row["symbol"].split(":")[1],
        "category": row["category"],
        "adjust": receipt["metadata"]["actual_adjust"],
        "asOf": _archive_time(receipt["metadata"]["last_closed_at"]).strftime("%Y-%m-%d %H:%M:%S"),
        "signalDate": _archive_time(row["signal_date"]).strftime("%Y-%m-%d %H:%M:%S")
        if row["signal_date"]
        else "",
        "signal": {"BUY": "买入", "SELL": "卖出", None: "无指定信号"}[row["latest_signal"]],
        "strategy": row["strategy"],
        "name": row["strategy_name"],
        "params": row["params"],
        "fingerprint": receipt["metadata"]["data_fingerprint"],
        "evidence": {"taskId": receipt["task_id"], "rowIndex": 0},
    }
    data = payload()
    data["target"] = {
        "kind": "stock",
        "market": row["symbol"].split(":")[0],
        "code": review["symbol"],
    }
    data["radarSource"] = {"contract": "radar-archive-v1", "review": review, "receipt": receipt}
    # The displayed chart can be an earlier replay prefix of the original scan.
    data["charts"][0].update(
        bars=copy.deepcopy(receipt["bars"][:-1]),
        category=row["category"],
        metadata=copy.deepcopy(receipt["metadata"]),
    )
    data["cutoff"] = data["charts"][0]["bars"][-1]["period_end"]
    return data


@pytest.mark.parametrize(
    "entry_id", [e["id"] for e in entries() if e["instrument"]["kind"] == "stock"]
)
def test_real_receipts_survive_standalone_sqlite_roundtrip_without_a_task(
    tmp_path, monkeypatch, entry_id
):
    data = radar_payload(entry_id)
    before = copy.deepcopy(data)
    monkeypatch.setattr(
        scan_evidence, "read_scan_evidence", lambda *a: pytest.fail("must not read task")
    )
    store = ResearchArchive(tmp_path / "archive.db")
    key = str(uuid.uuid4())
    record, created = store.create("alice", key, "chart", data, "原扫描复核")
    data["radarSource"]["receipt"]["bars"][0]["close"] = 999
    restored = ResearchArchive(store.path).get("alice", key)
    assert created and restored["payload"] == before
    assert restored["provenance"] == "client_archive_not_server_verified"
    assert record["digest"] == restored["digest"]
    assert len(before["charts"][0]["bars"]) + 1 == len(before["radarSource"]["receipt"]["bars"])


@pytest.mark.parametrize(
    "path,value",
    [
        (("contract",), "bad"),
        (("receipt", "task_id"), "b" * 32),
        (("review", "evidence", "rowIndex"), True),
        (("review", "symbol"), "300750"),
        (("review", "signalDate"), None),
        (("review", "asOf"), "2026-09-30T15:00:00"),
        (("receipt", "window_bars"), 0),
        (("receipt", "storage"), "missing"),
        (("receipt", "row", "params"), {"fast": 8}),
        (("receipt", "row", "latest_signal"), "SELL"),
        (("receipt", "row", "last_close"), 999),
        (("receipt", "row", "position"), "invalid"),
        (("receipt", "row", "metadata", "requested_adjust"), "NONE"),
        (("receipt", "metadata", "quality"), {"status": "error", "errors": ["bad"]}),
        (("receipt", "bars", 0, "is_closed"), False),
        (("receipt", "bars", 0, "vol"), -1),
        (("receipt", "bars", 0, "close"), "20"),
        (("receipt", "row", "recent_signals"), [{"date": "2020-01-01", "direction": "BUY"}]),
    ],
)
def test_inconsistent_lineage_is_rejected_atomically(tmp_path, path, value):
    data = radar_payload()
    item = data["radarSource"]
    for key in path[:-1]:
        item = item[key]
    item[path[-1]] = value
    store = ResearchArchive(tmp_path / "archive.db")
    with pytest.raises(ArchiveError) as caught:
        store.create("alice", str(uuid.uuid4()), "chart", data, "bad")
    assert caught.value.status == 422
    assert store.list("alice")["items"] == []


def test_multiple_signals_on_one_candle_and_window_smaller_than_signal_count(tmp_path):
    data = radar_payload()
    source = data["radarSource"]
    date = source["receipt"]["row"]["last_bar_date"]
    row = source["receipt"]["row"]
    row.update(
        recent_signals=[{"date": date, "direction": direction} for direction in ("SELL", "BUY")],
        latest_signal="BUY",
        signal_date=date,
    )
    source["receipt"]["window_bars"] = 1
    source["review"].update(
        signalDate=_archive_time(date).strftime("%Y-%m-%d %H:%M:%S"), signal="买入"
    )
    ResearchArchive(tmp_path / "archive.db").create(
        "alice", str(uuid.uuid4()), "chart", data, "双信号"
    )


@pytest.mark.parametrize(
    "category", ["MIN_1", "MIN_5", "MIN_15", "MIN_30", "MIN_60", "DAY", "WEEK", "MONTH"]
)
def test_archive_period_contract_matches_all_radar_review_periods(tmp_path, category):
    data = radar_payload()
    source = data["radarSource"]
    source["review"]["category"] = category
    source["receipt"]["row"]["category"] = category
    source["receipt"]["row"]["metadata"]["category"] = category
    source["receipt"]["metadata"]["category"] = category
    # Schema coverage, not a claim these daily fixture candles are real minute data.
    ResearchArchive(tmp_path / "archive.db").create(
        "alice", str(uuid.uuid4()), "chart", data, "周期契约"
    )


def test_cookie_upload_read_and_import_have_no_task_dependency(app_client, monkeypatch):
    client, _, sessions, _, _ = app_client
    data = radar_payload()
    monkeypatch.setattr(
        scan_evidence, "read_scan_evidence", lambda *a: pytest.fail("must not read task")
    )
    login(client, sessions)
    key = str(uuid.uuid4())
    url = f"/api/v1/research/archives/{key}"
    created = client.put(url, json={"kind": "chart", "payload": data, "name": "原扫描"})
    assert created.status_code == 201, created.text
    assert client.get(url).json()["payload"] == data
    for other in ("Bob", "Admin"):
        login(client, sessions, other)
        assert client.get(url).status_code == 404
    login(client, sessions)
    imported = client.put(
        f"/api/v1/research/archives/{uuid.uuid4()}",
        json={"kind": "chart", "payload": client.get(url).json()["payload"], "name": "导入"},
    )
    assert imported.status_code == 201
    assert imported.json()["provenance"] == "client_archive_not_server_verified"
