"""Staged storage acceptance; only temporary SQLite databases, no production writes."""

import copy
import multiprocessing
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from easy_tdx.web.research_archive import ArchiveError, ArchiveLimits, ResearchArchive


def payload():
    return {
        "schema": 1,
        "title": "宁德时代",
        "cutoff": "2026-10-09 15:00:00",
        "target": {"kind": "stock", "market": "SZ", "code": "300750"},
        "preferences": {"maPeriods": [5, 10]},
        "layers": {"bis": True},
        "charts": [
            {
                "category": "DAY",
                "bars": [
                    {
                        "datetime": "2026-10-09 00:00:00",
                        "open": 100.123456,
                        "close": 101,
                        "low": 99,
                        "high": 102,
                    }
                ],
                "metadata": {"actual_adjust": "QFQ", "source": "frozen-test"},
                "result": {
                    "bis": [],
                    "xds": [],
                    "zss": [],
                    "bcs": [],
                    "mmds": [],
                    "opaqueFutureField": {"version": 123},
                },
            }
        ],
    }


@pytest.fixture
def store(tmp_path):
    return ResearchArchive(tmp_path / "archive.db")


def error(status, fn):
    with pytest.raises(ArchiveError) as caught:
        fn()
    assert caught.value.status == status


def test_immutable_roundtrip_keeps_full_precision_and_unknown_rule_fields(store):
    source, key = payload(), str(uuid.uuid4())
    record, created = store.create("alice", key, "chart", source, "观察", "备注")
    source["charts"][0]["bars"][0]["close"] = 500
    restored = ResearchArchive(store.path).get("alice", key)
    assert created and restored["payload"] == payload()
    assert restored["digest"] == record["digest"]
    assert restored["provenance"] == "client_archive_not_server_verified"
    assert "payload" not in store.list("alice")["items"][0]
    assert "owner" not in record


def test_idempotent_create_does_not_overwrite_edited_metadata_or_restore_deleted(store):
    key = str(uuid.uuid4())
    row, _ = store.create("alice", key, "chart", payload(), "初始")
    row = store.mutate("alice", key, row["revision"], "edit", name="新版", note="新的备注")
    repeated, created = store.create("alice", key, "chart", payload(), "初始")
    assert not created and repeated == row
    row = store.mutate("alice", key, row["revision"], "delete")
    assert store.create("alice", key, "chart", payload(), "初始")[0] == row
    changed = payload()
    changed["title"] = "另一份"
    error(409, lambda: store.create("alice", key, "chart", changed, "覆盖"))


def test_owner_isolation_even_for_same_id_and_administrator(store):
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", payload(), "Alice")
    assert store.list("bob")["items"] == []
    for owner in ["bob", "admin", "alice' OR 1=1 --"]:
        error(404, lambda: store.get(owner, key))
        error(404, lambda: store.mutate(owner, key, 1, "delete"))
    store.create("bob", key, "chart", payload(), "Bob")
    assert store.get("alice", key)["name"] == "Alice"
    assert store.get("bob", key)["name"] == "Bob"


def test_revision_conflicts_are_atomic_and_do_not_change_immutable_payload(store):
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", payload(), "开始")
    edited = store.mutate("alice", key, 1, "edit", note="another device")
    error(409, lambda: store.mutate("alice", key, 1, "delete"))
    error(409, lambda: store.mutate("alice", key, 1, "edit", name="stale"))
    assert edited["revision"] == 2 and store.list("alice")["revision"] == 2
    assert store.get("alice", key)["payload"] == payload()
    assert store.mutate("alice", key, 2, "edit", note="another device")["revision"] == 2


def test_trash_restoration_and_purge_receipt_prevent_delayed_recreation(store):
    key = str(uuid.uuid4())
    row, _ = store.create("alice", key, "chart", payload(), "保留")
    before = store.list("alice")["quota"]["used_bytes"]
    error(409, lambda: store.mutate("alice", key, 1, "purge"))
    row = store.mutate("alice", key, 1, "delete")
    assert row["state"] == "deleted" and row["deleted_at"]
    assert store.get("alice", key)["payload"] == payload()
    assert store.list("alice")["quota"]["used_bytes"] == before
    row = store.mutate("alice", key, 2, "restore")
    assert row["state"] == "active" and row["deleted_at"] is None
    row = store.mutate("alice", key, 3, "delete")
    row = store.mutate("alice", key, 4, "purge")
    assert row["state"] == "purged" and row["size_bytes"] == 0
    assert store.list("alice")["items"] == []
    assert store.list("alice")["quota"]["used_bytes"] == 0
    error(410, lambda: store.get("alice", key))
    error(410, lambda: store.mutate("alice", key, 5, "restore"))
    error(410, lambda: store.create("alice", key, "chart", payload(), "保留"))


@pytest.mark.parametrize(
    "field,value", [("schema", True), ("charts", []), ("target", None), ("layers", None)]
)
def test_invalid_archive_shape_rejected_without_reservation(store, field, value):
    data = payload()
    data[field] = value
    error(422, lambda: store.create("alice", str(uuid.uuid4()), "chart", data, "bad"))
    assert store.list("alice")["revision"] == 0


@pytest.mark.parametrize(
    "mutation", ["nan", "infinity", "bool", "ohlc", "duplicate", "timezone", "date", "period"]
)
def test_malformed_bars_and_periods_rejected(store, mutation):
    data = payload()
    chart = data["charts"][0]
    bar = chart["bars"][0]
    if mutation == "nan":
        bar["open"] = float("nan")
    elif mutation == "infinity":
        bar["close"] = float("inf")
    elif mutation == "bool":
        bar["open"] = True
    elif mutation == "ohlc":
        bar["low"] = 103
    elif mutation == "duplicate":
        chart["bars"].append(dict(bar))
    elif mutation == "timezone":
        chart["bars"].append({**bar, "datetime": "2026-10-08T16:00:00Z"})  # Same instant.
    elif mutation == "date":
        bar["datetime"] = "2026-02-30"
    else:
        data["charts"].append(copy.deepcopy(chart))
    error(422, lambda: store.create("alice", str(uuid.uuid4()), "chart", data, "bad"))


def test_byte_quota_counts_utf8_metadata_and_trash(store):
    key = str(uuid.uuid4())
    created, _ = store.create("alice", key, "chart", payload(), "中")
    limit = replace(ArchiveLimits(), owner_bytes=created["size_bytes"])
    limited = ResearchArchive(store.path, limit)
    error(413, lambda: limited.mutate("alice", key, 1, "edit", name="中文"))
    assert limited.get("alice", key)["revision"] == 1
    limited.mutate("alice", key, 1, "delete")
    error(413, lambda: limited.create("alice", str(uuid.uuid4()), "chart", payload(), "新"))
    limited.mutate("alice", key, 2, "purge")
    assert limited.create("alice", str(uuid.uuid4()), "chart", payload(), "新")[1]


def test_object_and_receipt_caps_are_explicit(tmp_path):
    store = ResearchArchive(tmp_path / "bytes.db", replace(ArchiveLimits(), object_bytes=10))
    error(413, lambda: store.create("alice", str(uuid.uuid4()), "chart", payload(), "x"))
    store = ResearchArchive(tmp_path / "count.db", replace(ArchiveLimits(), owner_receipts=1))
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", payload(), "x")
    store.mutate("alice", key, 1, "delete")
    store.mutate("alice", key, 2, "purge")
    error(413, lambda: store.create("alice", str(uuid.uuid4()), "chart", payload(), "x"))


def test_content_corruption_fails_closed_and_audit_has_no_payload(store):
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", payload(), "private-name", "private-note")
    with sqlite3.connect(store.path) as db:
        audit = db.execute("SELECT * FROM archive_audit").fetchall()
        assert "private" not in repr(audit) and "300750" not in repr(audit)
        db.execute("UPDATE research_archives SET payload='{}' WHERE id=?", (key,))
    error(503, lambda: store.get("alice", key))


def test_unknown_future_database_version_is_not_downgraded(store):
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA user_version=99")
    error(503, lambda: ResearchArchive(store.path))
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_multi_period_research_roundtrip(store):
    chart = payload()["charts"][0]
    source = {
        "format": "chanlun-research-snapshot-v2",
        "as_of": "2026-10-09 15:00:00",
        "series": [
            {"category": "DAY", "snapshot": {"bars": chart["bars"], "metadata": chart["metadata"]}}
        ],
        "result": {
            "rows": [{"category": "DAY", "error": "样本不足"}],
            "parameters": {"window_bars": 20},
            "rule_version": "v-test",
        },
    }
    key = str(uuid.uuid4())
    store.create("alice", key, "study", source, "研究")
    assert store.get("alice", key)["payload"] == source


@pytest.mark.parametrize(
    "field,value",
    [
        ("datetime", "2026-02-30 00:00:00"),
        ("datetime", "2026-10-09"),
        ("datetime", "2026-10-09T12:00:00+01:60"),
        ("datetime", "2026-10-09T12:00:00+24:00"),
        ("datetime", "2026-10-09 24:00:00"),
        ("vol", "100"),
        ("amount", True),
        ("is_closed", "false"),
    ],
)
def test_archive_bar_calendar_volume_and_flags(store, field, value):
    source = payload()
    source["charts"][0]["bars"][0][field] = value
    error(422, lambda: store.create("alice", str(uuid.uuid4()), "chart", source, "bad"))
    assert not store.list("alice")["items"]


def test_archive_exchange_clock_and_explicit_offsets_keep_original_strings(store):
    source = payload()
    bars = source["charts"][0]["bars"]
    bars.append({**bars[0], "datetime": "2026-10-09T00:01:00Z"})
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", source, "原时钟")
    assert store.get("alice", key)["payload"] == source
    bars[1]["datetime"] = "2026-10-08T15:59:00Z"  # Earlier than exchange-local midnight.
    error(422, lambda: store.create("alice", str(uuid.uuid4()), "chart", source, "bad"))


@pytest.mark.parametrize(
    "case",
    [
        "rows_empty",
        "rows_duplicate",
        "series_duplicate",
        "missing_source",
        "bad_category",
        "bad_error",
        "cutoff",
    ],
)
def test_study_period_integrity_does_not_accept_partial_or_ambiguous_snapshot(store, case):
    chart = payload()["charts"][0]
    source = {
        "format": "chanlun-research-snapshot-v2",
        "as_of": "2026-10-09 15:00:00",
        "series": [
            {"category": "DAY", "snapshot": {"bars": chart["bars"], "metadata": chart["metadata"]}}
        ],
        "result": {"rows": [{"category": "DAY"}, {"category": "WEEK", "error": "数据不可用"}]},
    }
    if case == "rows_empty":
        source["result"]["rows"] = []
    elif case == "rows_duplicate":
        source["result"]["rows"].append(source["result"]["rows"][0])
    elif case == "series_duplicate":
        source["series"].append(source["series"][0])
    elif case == "missing_source":
        del source["result"]["rows"][1]["error"]
    elif case == "bad_category":
        source["series"][0]["category"] = {}
    elif case == "bad_error":
        source["result"]["rows"][1]["error"] = True
    else:
        source["as_of"] = "2026-02-30 15:00:00"
    error(422, lambda: store.create("alice", str(uuid.uuid4()), "study", source, "bad"))
    assert not store.list("alice")["items"]


@pytest.mark.parametrize("case", ["category", "target", "payload_unicode", "name_unicode"])
def test_untrusted_types_and_unicode_are_validation_errors(store, case):
    source, name = payload(), "x"
    if case == "category":
        source["charts"][0]["category"] = []
    elif case == "target":
        source["target"]["kind"] = {}
    elif case == "payload_unicode":
        source["title"] = "\ud800"
    else:
        name = "\ud800"
    error(422, lambda: store.create("alice", str(uuid.uuid4()), "chart", source, name))


def test_instance_capacity_applies_across_owners(store):
    _, _ = store.create("alice", str(uuid.uuid4()), "chart", payload(), "one")
    used = store.list("alice")["quota"]["used_bytes"]
    limited = ResearchArchive(store.path, replace(store.limits, instance_bytes=used))
    error(413, lambda: limited.create("bob", str(uuid.uuid4()), "chart", payload(), "two"))
    assert limited.list("bob")["items"] == []


def test_same_snapshot_id_cannot_change_family(store):
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", payload(), "one")
    # Different content on the same ID fails; original remains byte-for-byte unchanged.
    changed = payload()
    changed["charts"].append({**copy.deepcopy(changed["charts"][0]), "category": "WEEK"})
    error(409, lambda: store.create("alice", key, "chart", changed, "two"))
    assert store.get("alice", key)["payload"] == payload()


def test_sqlite_backup_restores_data_and_revisions_without_recomputation(store, tmp_path):
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", payload(), "original")
    store.mutate("alice", key, 1, "edit", note="saved note")
    backup = tmp_path / "restored.db"
    with sqlite3.connect(store.path) as original, sqlite3.connect(backup) as destination:
        original.backup(destination)
    restored = ResearchArchive(backup)
    assert restored.get("alice", key) == store.get("alice", key)
    assert restored.list("alice") == store.list("alice")


def _child(path, limits, action, key, gate, ready, result):
    try:
        store = ResearchArchive(Path(path), limits)
        ready.put(True)
        if not gate.wait(15):
            raise RuntimeError("barrier timed out")
        if action == "edit":
            item = store.mutate("alice", key, 1, "edit", note=str(uuid.uuid4()))
        else:
            item = store.create("alice", key, "chart", payload(), "concurrent")
        result.put((200, item))
    except ArchiveError as exc:
        result.put((exc.status, str(exc)))


def race(path, limits, actions):
    ctx = multiprocessing.get_context("spawn")
    gate, ready, results = ctx.Event(), ctx.Queue(), ctx.Queue()
    children = [
        ctx.Process(target=_child, args=(str(path), limits, action, key, gate, ready, results))
        for action, key in actions
    ]
    try:
        for p in children:
            p.start()
        for _ in children:
            assert ready.get(timeout=20)
        gate.set()
        output = [results.get(timeout=20) for _ in children]
        for p in children:
            p.join(10)
            assert p.exitcode == 0
        return output
    finally:
        for p in children:
            if p.is_alive():
                p.terminate()
                p.join(5)
        ready.close()
        results.close()
        ready.join_thread()
        results.join_thread()


def test_cross_process_create_is_idempotent(store):
    key = str(uuid.uuid4())
    output = race(store.path, store.limits, [("create", key), ("create", key)])
    assert [code for code, _ in output] == [200, 200]
    assert sorted(result[1] for _, result in output) == [False, True]
    assert store.list("alice")["revision"] == 1


def test_cross_process_cas_has_exactly_one_winner(store):
    key = str(uuid.uuid4())
    store.create("alice", key, "chart", payload(), "x")
    output = race(store.path, store.limits, [("edit", key), ("edit", key)])
    assert sorted(code for code, _ in output) == [200, 409]
    assert store.get("alice", key)["revision"] == 2


def test_cross_process_quota_has_exactly_one_winner(store):
    limits = replace(store.limits, owner_items=1)
    output = race(
        store.path, limits, [("create", str(uuid.uuid4())), ("create", str(uuid.uuid4()))]
    )
    assert sorted(code for code, _ in output) == [200, 413]
    assert store.list("alice")["quota"]["used_items"] == 1
