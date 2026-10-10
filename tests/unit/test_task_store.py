"""Persistent transactions and real spawned-process races; no production data."""

import multiprocessing
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from easy_tdx.web import task_store
from easy_tdx.web.task_payload import TaskInput, encode_task_input
from easy_tdx.web.task_store import StaleTaskLease, TaskLimits, TaskStore, TaskStoreFull

VERSION = "test-worker-v1"


def value(number=1, *, version=VERSION):
    return TaskInput("backtest", version, {"number": number}, (), {"adjust": "QFQ"})


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.db")


def _child(path, action, argument, ready, gate, output):
    store = TaskStore(Path(path))
    ready.put("ready")
    if not gate.wait(20):
        raise RuntimeError("test barrier timeout")
    try:
        if action == "submit":
            result = store.submit("alice", value())
        elif action == "submit_unique":
            try:
                result = store.submit("alice", value(argument))
            except TaskStoreFull:
                result = "full"
        elif action == "claim":
            result = store.claim(VERSION, "worker-" + str(argument))
        elif action == "get":
            result = store.get("alice", argument)
        elif action == "cancel":
            result = store.cancel("alice", argument)
        elif action == "finish":
            store.finish_after_exit(argument, result={"complete": True})
            result = "finished"
        else:
            raise AssertionError(action)
        output.put(("ok", result))
    except Exception as exc:
        output.put((type(exc).__name__, str(exc)))


def run_processes(path, *actions):
    context = multiprocessing.get_context("spawn")
    ready, output = context.Queue(), context.Queue()
    gate = context.Event()
    children = [
        context.Process(target=_child, args=(str(path), action, argument, ready, gate, output))
        for action, argument in actions
    ]
    try:
        for child in children:
            child.start()
        for _ in children:
            assert ready.get(timeout=20) == "ready"
        gate.set()
        results = [output.get(timeout=20) for _ in children]
        for child in children:
            child.join(timeout=10)
            assert child.exitcode == 0
        assert all(status == "ok" for status, _ in results), results
        return [result for _, result in results]
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        ready.close()
        output.close()
        ready.join_thread()
        output.join_thread()


def test_duplicate_submissions_from_two_processes_are_one_task(store):
    results = run_processes(store.path, ("submit", None), ("submit", None))
    assert len({record["task_id"] for record, _ in results}) == 1
    assert sorted(reused for _, reused in results) == [False, True]
    assert len(store.list_tasks("alice")) == 1


def test_two_processes_cannot_claim_one_task(store):
    record, _ = store.submit("alice", value())
    results = run_processes(store.path, ("claim", 1), ("claim", 2))
    leases = [lease for lease in results if lease is not None]
    assert len(leases) == 1
    assert leases[0].task_id == record["task_id"]
    assert store.get("alice", record["task_id"])["status"] == "running"


def test_database_limits_are_shared_across_processes(tmp_path):
    store = TaskStore(tmp_path / "shared.db", limits=TaskLimits(active_per_owner=1))
    results = run_processes(store.path, ("submit_unique", 1), ("submit_unique", 2))
    assert results.count("full") == 1
    assert len(store.list_tasks("alice")) == 1
    assert TaskStore(store.path).limits.active_per_owner == 1
    with pytest.raises(ValueError, match="不同配额"):
        TaskStore(store.path, limits=TaskLimits(active_per_owner=2))


def test_execution_slots_are_shared_across_processes(tmp_path):
    store = TaskStore(tmp_path / "slots.db", limits=TaskLimits(executing=1))
    store.submit("alice", value(1))
    store.submit("bob", value(2))
    results = run_processes(store.path, ("claim", 1), ("claim", 2))
    assert results.count(None) == 1
    assert (
        sum(
            row["status"] == "running"
            for owner in ("alice", "bob")
            for row in store.list_tasks(owner)
        )
        == 1
    )


def test_result_and_input_survive_a_fresh_process(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    assert store.load_input(lease, execution_version=VERSION) == value()
    result = {"complete": True, "price": 30.050000000000004, "count": 2**60}
    store.finish_after_exit(lease, result=result)
    restored = run_processes(store.path, ("get", record["task_id"]))[0]
    assert restored["status"] == "done"
    assert restored["result"] == result


def test_cancel_result_race_never_exposes_result_of_cancelled_task(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    run_processes(store.path, ("cancel", record["task_id"]), ("finish", lease))
    result = store.get("alice", record["task_id"])
    assert result["status"] in {"done", "cancelled"}
    assert result["result"] == ({"complete": True} if result["status"] == "done" else None)


def test_owner_isolation_including_admin_and_no_internal_payload_leaks(store):
    original, _ = store.submit("alice", value())
    other, reused = store.submit("bob", value())
    assert not reused
    assert other["task_id"] != original["task_id"]
    for stranger in ("bob", "admin", "unknown"):
        with pytest.raises(KeyError):
            store.get(stranger, original["task_id"])
        with pytest.raises(KeyError):
            store.cancel(stranger, original["task_id"])
        with pytest.raises(KeyError):
            store.delete(stranger, original["task_id"])
    assert len(store.list_tasks("alice")) == len(store.list_tasks("bob")) == 1
    assert store.list_tasks("admin") == []
    assert set(store.get("alice", original["task_id"])) == {
        "task_id",
        "status",
        "description",
        "created_at",
        "started_at",
        "finished_at",
        "elapsed",
        "error",
        "recovery_count",
        "last_recovery_at",
        "last_recovery_reason",
        "kind",
        "progress",
        "execution_compatible",
        "checkpoint_grid_points",
        "resumed_grid_points",
        "checkpoint_scan_targets",
        "resumed_scan_targets",
        "checkpoint_signal_bars",
        "resumed_signal_bars",
        "checkpoint_order_signals",
        "resumed_order_signals",
        "checkpoint_pnl_trades",
        "resumed_pnl_trades",
        "checkpoint_equity_bars",
        "resumed_equity_bars",
        "result",
    }


def test_cancellation_keeps_execution_and_active_quota_until_exit(tmp_path):
    store = TaskStore(
        tmp_path / "quota.db", limits=TaskLimits(active=2, active_per_owner=1, executing=1)
    )
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    store.submit("bob", value(2))
    assert store.cancel("alice", record["task_id"])["status"] == "cancelling"
    assert store.heartbeat(lease) == "cancelled"
    assert store.claim(VERSION, "second") is None
    with pytest.raises(TaskStoreFull, match="活动"):
        store.submit("alice", value(3))
    with pytest.raises(ValueError, match="不能删除"):
        store.delete("alice", record["task_id"])
    store.finish_after_exit(lease, result={"should_not_publish": True})
    assert store.get("alice", record["task_id"])["status"] == "cancelled"
    assert store.get("alice", record["task_id"])["result"] is None
    assert store.claim(VERSION, "second") is not None


def test_pending_cancel_is_terminal_and_never_claimed(store):
    record, _ = store.submit("alice", value())
    assert store.cancel("alice", record["task_id"])["status"] == "cancelled"
    assert store.cancel("alice", record["task_id"])["status"] == "cancelled"
    assert store.claim(VERSION, "test-worker") is None
    new_record, reused = store.submit("alice", value())
    assert not reused and new_record["task_id"] != record["task_id"]


def test_stale_heartbeat_does_not_imply_death_or_release(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    with store.connect() as conn:
        conn.execute("UPDATE tasks SET heartbeat=0 WHERE id=?", (record["task_id"],))
    assert store.stalled(before=time.time()) == [lease]
    assert store.get("alice", record["task_id"])["status"] == "running"
    assert store.claim(VERSION, "other") is None
    assert store.heartbeat(lease) is None


def test_restart_fences_old_worker_and_preserves_frozen_input(store):
    record, _ = store.submit("alice", value())
    old = store.claim(VERSION, "old")
    store.requeue_after_exit(old)
    new = store.claim(VERSION, "new")
    assert new.generation == old.generation + 1 and new.token != old.token
    for operation in (
        lambda: store.heartbeat(old),
        lambda: store.load_input(old, execution_version=VERSION),
        lambda: store.finish_after_exit(old, result={"obsolete": True}),
        lambda: store.requeue_after_exit(old),
        lambda: store.request_timeout(old),
    ):
        with pytest.raises(StaleTaskLease):
            operation()
    assert store.load_input(new, execution_version=VERSION) == value()
    store.finish_after_exit(new, result={"fresh": True})
    assert store.get("alice", record["task_id"])["result"] == {"fresh": True}


@pytest.mark.parametrize("stop", ["cancelled", "timed_out"])
def test_recovery_does_not_resurrect_cancelled_or_timed_out_work(store, stop):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    if stop == "cancelled":
        store.cancel("alice", record["task_id"])
    else:
        store.request_timeout(lease)
    store.requeue_after_exit(lease)
    assert store.get("alice", record["task_id"])["status"] == stop
    assert store.claim(VERSION, "test-worker") is None


def test_timeout_keeps_first_stop_reason_and_discards_late_results(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    store.request_timeout(lease)
    store.cancel("alice", record["task_id"])
    assert store.heartbeat(lease) == "timed_out"
    store.finish_after_exit(lease, result={"partial": True})
    assert store.get("alice", record["task_id"])["status"] == "timed_out"
    assert store.get("alice", record["task_id"])["result"] is None


def test_exact_owner_input_version_cache_and_explicit_fresh_run(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    store.finish_after_exit(lease, result={"complete": True})
    assert store.submit("alice", value()) == (store.list_tasks("alice")[0], True)
    fresh, reused = store.submit("alice", value(), use_cache=False)
    assert not reused and fresh["task_id"] != record["task_id"]
    # Active work is coalesced even if completed-result reuse was disabled.
    assert store.submit("alice", value(), use_cache=False)[1]
    changed, reused = store.submit("alice", value(version="v2"))
    assert not reused and changed["task_id"] != record["task_id"]
    assert store.claim("unknown-version", "test-worker") is None


def test_input_tampering_or_version_mismatch_rejected(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    with pytest.raises(ValueError, match="执行版本"):
        store.load_input(lease, execution_version="v2")
    with store.connect() as conn:
        conn.execute("UPDATE tasks SET payload=? WHERE id=?", (b"{}", record["task_id"]))
    with pytest.raises(ValueError, match="指纹"):
        store.load_input(lease, execution_version=VERSION)


def test_control_plane_queries_do_not_load_large_input_blobs(store, monkeypatch):
    record, _ = store.submit("alice", value())
    connect = store.connect

    @contextmanager
    def no_payload_reads():
        with connect() as conn:
            conn.set_authorizer(
                lambda action, table, column, db, source: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_READ and table == "tasks" and column == "payload"
                    else sqlite3.SQLITE_OK
                )
            )
            yield conn

    monkeypatch.setattr(store, "connect", no_payload_reads)
    assert len(store.list_tasks("alice")) == 1
    assert store.get("alice", record["task_id"])["status"] == "pending"
    assert store.submit("alice", value())[1]
    lease = store.claim(VERSION, "test-worker")
    assert store.heartbeat(lease) is None
    assert store.stalled(before=time.time()) == [lease]
    assert store.cancel("alice", record["task_id"])["status"] == "cancelling"
    with pytest.raises(sqlite3.DatabaseError, match="prohibited"):
        store.load_input(lease, execution_version=VERSION)


def test_global_and_owner_record_retention_never_evict_active_work(tmp_path):
    limits = TaskLimits(records=2, records_per_owner=1)
    store = TaskStore(tmp_path / "records.db", limits=limits)
    first, _ = store.submit("alice", value())
    with pytest.raises(TaskStoreFull, match="保留数量"):
        store.submit("alice", value(2))
    store.cancel("alice", first["task_id"])
    with pytest.raises(TaskStoreFull, match="保留数量"):
        store.submit("alice", value(2))
    store.submit("bob", value())
    with pytest.raises(TaskStoreFull, match="保留数量"):
        store.submit("carol", value())
    store.delete("alice", first["task_id"])
    assert not store.submit("alice", value(2))[1]


def test_storage_quota_submission_and_result_failure_are_explicit(tmp_path):
    size = len(encode_task_input(value()))
    limits = TaskLimits(retained_bytes=2 * size, retained_bytes_per_owner=size)
    store = TaskStore(tmp_path / "bytes.db", limits=limits)
    record, _ = store.submit("alice", value())
    with pytest.raises(TaskStoreFull, match="存储"):
        store.submit("alice", value(2))
    lease = store.claim(VERSION, "test-worker")
    store.finish_after_exit(lease, result={"cannot_fit": True})
    result = store.get("alice", record["task_id"])
    assert result["status"] == "failed"
    assert "存储配额" in result["error"]
    assert result["result"] is None
    store.delete("alice", record["task_id"])
    assert not store.submit("alice", value())[1]


@pytest.mark.parametrize(
    "result", [{"nan": float("nan")}, {"value": object()}, {1: "key"}, {"tuple": (1, 2)}]
)
def test_non_json_results_are_failed_not_successful_or_partially_saved(store, result):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    store.finish_after_exit(lease, result=result)
    result = store.get("alice", record["task_id"])
    assert result["status"] == "failed" and result["result"] is None
    assert "安全保存" in result["error"]


def test_size_limit_failure_does_not_publish_partial_result(store, monkeypatch):
    monkeypatch.setattr(task_store, "MAX_RESULT_BYTES", 5)
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    store.finish_after_exit(lease, result={"complete": True})
    assert store.get("alice", record["task_id"])["status"] == "failed"


def test_failed_serialization_and_database_write_leave_no_phantom_task(store):
    with pytest.raises(ValueError):
        store.submit("alice", replace(value(), context={"not_serializable": object()}))
    assert store.list_tasks("alice") == []
    with store.connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_write BEFORE INSERT ON tasks "
            "BEGIN SELECT RAISE(ABORT, 'test disk failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="test disk failure"):
        store.submit("alice", value())
    assert store.list_tasks("alice") == []
    with store.connect() as conn:
        conn.execute("DROP TRIGGER fail_write")
    assert not store.submit("alice", value())[1]


def test_result_commit_failure_keeps_state_and_can_retry_after_same_observed_exit(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    with store.connect() as conn:
        conn.execute(
            "CREATE TRIGGER fail_result BEFORE UPDATE OF result ON tasks "
            "BEGIN SELECT RAISE(ABORT, 'test result write failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="test result write failure"):
        store.finish_after_exit(lease, result={"complete": True})
    pending = store.get("alice", record["task_id"])
    assert pending["status"] == "running" and pending["result"] is None
    with store.connect() as conn:
        conn.execute("DROP TRIGGER fail_result")
    store.finish_after_exit(lease, result={"complete": True})
    assert store.get("alice", record["task_id"])["status"] == "done"
    with pytest.raises(StaleTaskLease):
        store.finish_after_exit(lease, result={"different": True})


def test_failed_jobs_are_not_cached_and_completed_jobs_cannot_be_cancelled(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    store.finish_after_exit(lease, error="explicit failure")
    failed = store.get("alice", record["task_id"])
    assert failed["status"] == "failed" and failed["error"] == "explicit failure"
    assert store.cancel("alice", record["task_id"])["status"] == "failed"
    fresh, reused = store.submit("alice", value())
    assert not reused and fresh["task_id"] != record["task_id"]


@pytest.mark.parametrize(
    "kwargs", [{}, {"result": {}, "error": "both"}, {"error": ""}, {"result": []}]
)
def test_invalid_completion_contract_does_not_change_active_state(store, kwargs):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "test-worker")
    with pytest.raises(ValueError):
        store.finish_after_exit(lease, **kwargs)
    assert store.get("alice", record["task_id"])["status"] == "running"


def test_foreign_database_and_newer_schema_are_not_overwritten(tmp_path):
    path = tmp_path / "unrelated.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE user_data(value TEXT)")
        conn.execute("INSERT INTO user_data VALUES ('preserve')")
    with pytest.raises(ValueError, match="其他用途"):
        TaskStore(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM user_data").fetchone()[0] == "preserve"
        conn.execute("PRAGMA user_version=1")
    with pytest.raises(ValueError, match="结构不匹配"):
        TaskStore(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="不兼容"):
        TaskStore(path)


def test_dataframe_input_and_metadata_survive_database_restart(store):
    frame = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=3),
            "close": [30.050000000000004, 29.02, 31.11],
        }
    )
    frame.attrs = {"snapshot_metadata": {"actual_adjust": "QFQ", "source": "fixture"}}
    store.submit("alice", replace(value(), frames=(frame,)))
    restarted = TaskStore(store.path)
    lease = restarted.claim(VERSION, "test-worker")
    restored = restarted.load_input(lease, execution_version=VERSION)
    pd.testing.assert_frame_equal(restored.frames[0], frame, check_exact=True)
    assert restored.frames[0].attrs == frame.attrs


@pytest.mark.parametrize(
    "limits", [{"active": True}, {"executing": 0}, {"records": -1}, {"retained_bytes": 1.5}]
)
def test_invalid_limits(limits):
    with pytest.raises(ValueError):
        TaskLimits(**limits)


def test_staged_outcome_remains_private_until_exit_and_uses_quota(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "worker")
    store.stage_result(lease, result={"complete": True})
    visible = TaskStore(store.path).get("alice", record["task_id"])
    assert visible["status"] == "running" and visible["result"] is None
    with store.connect() as conn:
        assert conn.execute(
            "SELECT retained_bytes=length(payload)+length(staged_result) FROM tasks"
        ).fetchone()[0]
    store.finish_staged_after_exit(lease, 0)
    assert store.get("alice", record["task_id"])["result"] == {"complete": True}
    with store.connect() as conn:
        row = conn.execute(
            "SELECT staged_result,retained_bytes=length(payload)+length(result) AS exact FROM tasks"
        ).fetchone()
        assert row["staged_result"] is None and row["exact"]


@pytest.mark.parametrize("exit_code", [0, 1, -9])
def test_staged_result_never_overrides_cancel_intent(store, exit_code):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "worker")
    store.stage_result(lease, result={"late": True})
    store.cancel("alice", record["task_id"])
    store.finish_staged_after_exit(lease, exit_code)
    result = store.get("alice", record["task_id"])
    assert result["status"] == "cancelled" and result["result"] is None
    with store.connect() as conn:
        assert conn.execute(
            "SELECT staged_result IS NULL AND retained_bytes=length(payload) FROM tasks"
        ).fetchone()[0]


def test_abnormal_exit_discards_even_a_staged_success(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "worker")
    store.stage_result(lease, result={"complete": True})
    store.finish_staged_after_exit(lease, -9)
    result = store.get("alice", record["task_id"])
    assert result["status"] == "failed" and result["result"] is None


def test_staged_failure_and_missing_outcome_are_not_success(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "worker")
    store.stage_result(lease, error="明确失败")
    store.finish_staged_after_exit(lease, 0)
    assert store.get("alice", record["task_id"])["error"] == "明确失败"
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "worker")
    store.finish_staged_after_exit(lease, 0)
    assert store.get("alice", record["task_id"])["status"] == "failed"


def test_requeue_clears_staged_result_and_old_generation_cannot_restage(store):
    record, _ = store.submit("alice", value())
    lease = store.claim(VERSION, "worker")
    store.stage_result(lease, result={"old": True})
    store.requeue_after_exit(lease)
    with store.connect() as conn:
        assert conn.execute(
            "SELECT staged_result IS NULL AND retained_bytes=length(payload) FROM tasks"
        ).fetchone()[0]
    fresh = store.claim(VERSION, "new")
    with pytest.raises(StaleTaskLease):
        store.stage_result(lease, result={"stale": True})
    store.stage_result(fresh, result={"new": True})
    store.finish_staged_after_exit(fresh, 0)
    assert store.get("alice", record["task_id"])["result"] == {"new": True}


@pytest.mark.parametrize("source_version", [1, 2, 3, 4, 5, 6, 7])
def test_old_database_migration_preserves_input_result_owner_and_limits(tmp_path, source_version):
    import json

    from easy_tdx.web.task_payload import input_fingerprint

    path = tmp_path / "v1.db"
    payload = encode_task_input(value())
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE tasks (
            id TEXT PRIMARY KEY,owner TEXT,fingerprint TEXT,version TEXT,kind TEXT,payload BLOB,
            status TEXT,description TEXT,created_at REAL,started_at REAL,finished_at REAL,
            heartbeat REAL,generation INTEGER,lease TEXT,worker_id TEXT,result BLOB,error TEXT,
            stop_reason TEXT,retained_bytes INTEGER)""")
        conn.execute("CREATE TABLE task_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO task_settings VALUES ('limits',?)",
            (json.dumps(vars(TaskLimits(executing=2))),),
        )
        for task_id, status, result in (
            ("old-complete", "done", b'{"preserved":true}'),
            ("old-pending", "pending", None),
        ):
            conn.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    "alice",
                    input_fingerprint(payload),
                    VERSION,
                    "backtest",
                    payload,
                    status,
                    "old description",
                    1,
                    None,
                    None,
                    None,
                    0,
                    None,
                    None,
                    result,
                    None,
                    None,
                    len(payload) + len(result or b""),
                ),
            )
        if source_version >= 2:
            conn.execute("ALTER TABLE tasks ADD COLUMN staged_result BLOB")
            conn.execute("ALTER TABLE tasks ADD COLUMN staged_error TEXT")
            conn.execute("ALTER TABLE tasks ADD COLUMN staged_status TEXT")
        if source_version >= 3:
            conn.execute("ALTER TABLE tasks ADD COLUMN guard_protocol TEXT")
            conn.execute("ALTER TABLE tasks ADD COLUMN guard_ready INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE tasks ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE tasks ADD COLUMN last_recovery_at REAL")
            conn.execute("ALTER TABLE tasks ADD COLUMN last_recovery_reason TEXT")
        if source_version >= 4:
            conn.execute("ALTER TABLE tasks ADD COLUMN checkpoint BLOB")
            conn.execute("ALTER TABLE tasks ADD COLUMN checkpoint_fingerprint TEXT")
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN checkpoint_grid_points INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN resumed_grid_points INTEGER NOT NULL DEFAULT 0"
            )
        if source_version >= 5:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN checkpoint_scan_targets INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN resumed_scan_targets INTEGER NOT NULL DEFAULT 0"
            )
        if source_version >= 6:
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN checkpoint_signal_bars INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE tasks ADD COLUMN resumed_signal_bars INTEGER NOT NULL DEFAULT 0"
            )
        if source_version >= 7:
            for unit in ("order_signals", "pnl_trades", "equity_bars"):
                for prefix in ("checkpoint", "resumed"):
                    conn.execute(
                        f"ALTER TABLE tasks ADD COLUMN {prefix}_{unit} INTEGER NOT NULL DEFAULT 0"
                    )
        conn.execute(f"PRAGMA user_version={source_version}")
    migrated = TaskStore(path)
    assert migrated.limits.executing == 2
    assert migrated.get("alice", "old-complete")["result"] == {"preserved": True}
    assert migrated.get("alice", "old-complete")["progress"] is None
    with pytest.raises(KeyError):
        migrated.get("bob", "old-complete")
    lease = migrated.claim(VERSION, "worker")
    assert lease.task_id == "old-pending"
    assert migrated.load_input(lease, execution_version=VERSION) == value()
    with migrated.connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert TaskStore(path).get("alice", "old-complete")["result"] == {"preserved": True}
