"""Attached-db transactions: races, rollback, crash recovery and safe modes."""

import multiprocessing
import sqlite3
from pathlib import Path

import pytest

from easy_tdx.web.account_store import AccountStore
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import TaskStore


@pytest.fixture
def stores(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.db")
    tasks = TaskStore(tmp_path / "tasks.db")
    record, _ = tasks.submit("alice", TaskInput("backtest", "v1", {}, (), {}))
    return accounts, tasks, record["task_id"]


def _cancel(path, task_id, gate, ready, output):
    store = TaskStore(Path(path))
    ready.put(True)
    assert gate.wait(15)
    state = store.cancel("alice", task_id, account_db=Path(path).with_name("accounts.db"))
    output.put(state["status"])


def test_concurrent_cancel_records_only_actual_transition(stores):
    accounts, tasks, task_id = stores
    context = multiprocessing.get_context("spawn")
    gate, ready, output = context.Event(), context.Queue(), context.Queue()
    children = [
        context.Process(target=_cancel, args=(tasks.path, task_id, gate, ready, output))
        for _ in range(2)
    ]
    try:
        for child in children:
            child.start()
        assert all(ready.get(timeout=20) for _ in children)
        gate.set()
        assert [output.get(timeout=20) for _ in children] == ["cancelled", "cancelled"]
        for child in children:
            child.join(10)
            assert child.exitcode == 0
        events = accounts.list_audit(action="task_cancel")["items"]
        assert len(events) == 1 and events[0]["details"] == {"task_id": task_id}
    finally:
        for child in children:
            if child.is_alive():
                child.kill()
                child.join(5)
        for queue in (ready, output):
            queue.close()
            queue.join_thread()


@pytest.mark.parametrize("database", ["tasks", "accounts"])
def test_wal_rejected_without_mutation_or_silent_mode_change(stores, database):
    accounts, tasks, task_id = stores
    path = tasks.path if database == "tasks" else accounts.db_path
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    with pytest.raises(sqlite3.OperationalError, match="回滚日志"):
        tasks.cancel("alice", task_id, account_db=accounts.db_path)
    assert tasks.summary("alice", task_id)["status"] == "pending"
    assert accounts.list_audit()["items"] == []
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.parametrize("operation", ["cancel", "delete"])
def test_audit_cleanup_failure_rolls_back_event_and_mutation(stores, operation):
    accounts, tasks, task_id = stores
    accounts.audit_login(None)
    if operation == "delete":
        tasks.cancel("alice", task_id)
    before = tasks.summary("alice", task_id)["status"]
    with accounts._connect() as conn:
        conn.execute("UPDATE account_audit SET id=10001")
        conn.execute(
            "INSERT INTO account_audit (id,occurred_at,action,outcome) "
            "VALUES (1,'2026-10-09T00:00:00Z','login','denied')"
        )
        conn.execute(
            "CREATE TRIGGER reject_cleanup BEFORE DELETE ON account_audit "
            "BEGIN SELECT RAISE(ABORT, 'cleanup failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        getattr(tasks, operation)("alice", task_id, account_db=accounts.db_path)
    assert tasks.summary("alice", task_id)["status"] == before
    assert accounts.list_audit(action="task_" + operation)["items"] == []
    assert len(accounts.list_audit()["items"]) == 2


def test_foreign_and_unfinished_operations_have_no_success_audit(stores):
    accounts, tasks, task_id = stores
    for action in (tasks.cancel, tasks.delete):
        with pytest.raises(KeyError):
            action("bob", task_id, account_db=accounts.db_path)
    with pytest.raises(ValueError, match="不能删除"):
        tasks.delete("alice", task_id, account_db=accounts.db_path)
    assert accounts.list_audit()["items"] == []


def test_running_cancel_is_audited_once_without_releasing_execution(stores):
    accounts, tasks, task_id = stores
    lease = tasks.claim("v1", "worker")
    for _ in range(2):
        assert tasks.cancel("alice", task_id, account_db=accounts.db_path)["status"] == "cancelling"
    assert len(accounts.list_audit(action="task_cancel")["items"]) == 1
    tasks.finish_after_exit(lease, result={"late": True})
    assert tasks.get("alice", task_id)["status"] == "cancelled"
    assert tasks.get("alice", task_id)["result"] is None


def _crash_during_audit(path, task_id, ready):
    from easy_tdx.web import task_store

    original = task_store.record_task_operation

    def hold(conn, *args):
        original(conn, *args)
        ready.set()
        # Parent kills this known child while both changes are uncommitted.
        multiprocessing.Event().wait(30)
        raise AssertionError("parent failed to kill crash fixture")

    task_store.record_task_operation = hold
    TaskStore(Path(path)).cancel("alice", task_id, account_db=Path(path).with_name("accounts.db"))


def test_process_death_before_commit_leaves_neither_half_operation(stores):
    accounts, tasks, task_id = stores
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    child = context.Process(target=_crash_during_audit, args=(tasks.path, task_id, ready))
    try:
        child.start()
        assert ready.wait(20)
        child.kill()
        child.join(10)
        assert child.exitcode is not None and child.exitcode != 0
        assert TaskStore(tasks.path).summary("alice", task_id)["status"] == "pending"
        assert AccountStore(accounts.db_path).list_audit()["items"] == []
        tasks.cancel("alice", task_id, account_db=accounts.db_path)
        assert len(accounts.list_audit(action="task_cancel")["items"]) == 1
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)


def test_missing_or_other_directory_account_db_is_not_created(stores, tmp_path):
    _, tasks, task_id = stores
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        tasks.cancel("alice", task_id, account_db=missing)
    assert not missing.exists()
    other = AccountStore(tmp_path / "other" / "accounts.db")
    with pytest.raises(sqlite3.OperationalError):
        tasks.cancel("alice", task_id, account_db=other.db_path)
    assert tasks.summary("alice", task_id)["status"] == "pending"
