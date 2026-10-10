"""OS liveness evidence, cold restarts and crash windows on private local files."""

import multiprocessing
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.web.routers.backtest import _ohlcv_to_df
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_guard import (
    GUARD_PROTOCOL,
    TaskGuard,
    UnsafeTaskGuard,
    guard_path,
    verify_inherited_guard,
)
from easy_tdx.web.task_payload import TaskInput
from easy_tdx.web.task_store import StaleTaskLease, TaskLease, TaskLimits, TaskStore
from easy_tdx.web.task_supervisor import TaskSupervisor

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX liveness guards")


def _value(version):
    prices = 30 + np.sin(np.arange(80) / 3)
    frame = pd.DataFrame(
        dict(
            datetime=pd.bdate_range("2026-01-05", periods=80),
            open=prices,
            close=prices,
            high=prices + 1,
            low=prices - 1,
            vol=np.ones(80) * 10000,
            amount=prices * 10000,
        ),
    )
    frame = _ohlcv_to_df(frame.to_dict("records"))
    return TaskInput(
        "backtest",
        version,
        {
            "strategy": "ma_cross",
            "symbol": "SZ:300750",
            "params": {"fast": 5, "slow": 10},
        },
        (frame,),
        {},
    )


@pytest.fixture
def store(tmp_path):
    return TaskStore(tmp_path / "tasks.db", limits=TaskLimits(executing=1))


@pytest.fixture
def supervisor(store):
    instance = TaskSupervisor(store, owner_active=lambda owner: True)
    yield instance
    instance.close()


def _claim(store, supervisor, *, ready=False, create=True):
    record, _ = store.submit("alice", _value(supervisor.version))
    owner = "abandoned-owner"
    owner_guard = TaskGuard.acquire(guard_path(store.path, owner), create=True)
    lease = store.claim(supervisor.version, owner, guard_protocol=GUARD_PROTOCOL)
    attempt = None
    if create:
        attempt = TaskGuard.acquire(guard_path(store.path, owner, lease), create=True)
    if ready:
        store.mark_guard_ready(lease)
    return record, lease, owner_guard, attempt


@pytest.mark.parametrize("ready,create", [(False, False), (False, True), (True, True)])
def test_claim_to_spawn_crash_windows_restart_frozen_input(store, supervisor, ready, create):
    record, lease, owner, attempt = _claim(store, supervisor, ready=ready, create=create)
    assert supervisor.recover() == 0  # An alive owner cannot lose its claim.
    owner.close()
    if attempt:
        assert supervisor.recover() == 0
        attempt.close()
    assert supervisor.recover() == 1
    assert supervisor.recover() == 0
    state = store.get("alice", record["task_id"])
    assert state["status"] == "pending" and state["recovery_count"] == 1
    assert state["last_recovery_reason"] == "supervisor_lost"
    assert state["last_recovery_at"] is not None
    with pytest.raises(StaleTaskLease):
        store.heartbeat(lease)
    fresh = store.claim(supervisor.version, "new-owner")
    assert fresh.generation == lease.generation + 1
    with pytest.raises(StaleTaskLease):
        store.stage_result(lease, result={"late": True})
    with pytest.raises(StaleTaskLease):
        store.load_input(lease, execution_version=supervisor.version)


@pytest.mark.parametrize("intent", ["cancelled", "timed_out"])
def test_abandoned_stop_intent_stays_terminal_never_restarts(store, supervisor, intent):
    record, lease, owner, attempt = _claim(store, supervisor, ready=True)
    store.stage_result(lease, result={"private": True})
    if intent == "cancelled":
        store.cancel("alice", record["task_id"])
    else:
        store.request_timeout(lease)
    owner.close()
    attempt.close()
    assert supervisor.recover() == 1
    state = store.get("alice", record["task_id"])
    assert state["status"] == intent and state["result"] is None
    assert state["recovery_count"] == 0
    assert store.claim(supervisor.version, "new") is None


def test_unknown_exit_does_not_publish_private_staged_success(store, supervisor):
    record, lease, owner, attempt = _claim(store, supervisor, ready=True)
    store.stage_result(lease, result={"not_proven_successful_exit": True})
    owner.close()
    attempt.close()
    assert supervisor.recover() == 1
    state = store.get("alice", record["task_id"])
    assert state["status"] == "pending" and state["result"] is None
    with store.connect() as conn:
        assert conn.execute("SELECT staged_result FROM tasks").fetchone()[0] is None


def test_stale_heartbeat_never_reclaims_living_owner(store, supervisor):
    record, lease, owner, attempt = _claim(store, supervisor, ready=True)
    try:
        attempt.close()  # Even an exited child still belongs to its living supervisor.
        with store.connect() as conn:
            conn.execute("UPDATE tasks SET heartbeat=-1000000")
        assert supervisor.recover() == 0
        assert store.get("alice", record["task_id"])["status"] == "running"
    finally:
        owner.close()
        attempt.close()


@pytest.mark.parametrize("missing", ["owner", "ready_attempt"])
def test_missing_proof_fails_closed(store, supervisor, missing):
    record, lease, owner, attempt = _claim(store, supervisor, ready=True)
    owner.close()
    attempt.close()
    path = guard_path(store.path, lease.worker_id, lease if missing == "ready_attempt" else None)
    path.unlink()  # Deliberate corruption of this test's private guard only.
    assert supervisor.recover() == 0
    assert "异常" in supervisor.recovery_issues[record["task_id"]]
    assert store.get("alice", record["task_id"])["status"] == "running"


def test_legacy_claim_has_no_implicit_death_proof(store, supervisor):
    record, _ = store.submit("alice", _value(supervisor.version))
    store.claim(supervisor.version, "legacy-owner")
    assert supervisor.recover() == 0
    assert "无存活证明" in supervisor.recovery_issues[record["task_id"]]


def test_guard_ready_is_once_only_and_fenced(store, supervisor):
    _, lease, owner, attempt = _claim(store, supervisor)
    try:
        store.mark_guard_ready(lease)
        with pytest.raises(ValueError, match="已准备"):
            store.mark_guard_ready(lease)
    finally:
        owner.close()
        attempt.close()
    supervisor.recover()
    with pytest.raises(StaleTaskLease):
        store.mark_guard_ready(lease)


def test_inherited_attempt_stays_locked_after_owner_death_and_parent_close(store, supervisor):
    record, lease, owner, attempt = _claim(store, supervisor, ready=True)
    code = (
        "import sys; from pathlib import Path; "
        "from easy_tdx.web.task_guard import verify_inherited_guard; "
        "verify_inherited_guard(int(sys.argv[1]), Path(sys.argv[2])); "
        "print('locked', flush=True); sys.stdin.buffer.read()"
    )
    path = guard_path(store.path, lease.worker_id, lease)
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(attempt.fd), str(path)],
        pass_fds=(attempt.fd,),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        assert child.stdout.readline() == b"locked\n"
        attempt.close()
        owner.close()
        child.send_signal(signal.SIGSTOP)
        assert supervisor.recover() == 0
        assert "仍持有" in supervisor.recovery_issues[record["task_id"]]
        assert store.claim(supervisor.version, "competing") is None
        child.kill()
        child.wait(timeout=5)
        assert supervisor.recover() == 1
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()
        owner.close()
        attempt.close()


def _crash_owner(path, pipe):
    store = TaskStore(Path(path))
    supervisor = TaskSupervisor(store, owner_active=lambda owner: True)
    supervisor.step()
    running = next(iter(supervisor._running.values()))
    pipe.send(asdict(running.lease))
    pipe.recv()  # Test kills this actual service without calling close().


def test_actual_supervisor_sigkill_cold_restart_completes_same_frozen_calculation(
    store, supervisor
):
    value = _value(supervisor.version)
    expected = dispatch_task(value)
    record, _ = store.submit("alice", value)
    context = multiprocessing.get_context("spawn")
    parent, peer = context.Pipe()
    owner = context.Process(target=_crash_owner, args=(str(store.path), peer))
    owner.start()
    try:
        assert parent.poll(15)
        lease = TaskLease(**parent.recv())
        assert supervisor.recover() == 0
        owner.kill()
        owner.join(5)
        assert owner.exitcode == -signal.SIGKILL
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            supervisor.step()
            state = store.get("alice", record["task_id"])
            if state["status"] == "done":
                break
            time.sleep(0.02)
        assert state["status"] == "done", state
        assert state["result"] == expected
        assert state["recovery_count"] == 1
        with pytest.raises(StaleTaskLease):
            store.heartbeat(lease)
    finally:
        if owner.is_alive():
            owner.kill()
        owner.join(5)
        parent.close()
        peer.close()


def _recover_racer(path, gate, output):
    supervisor = TaskSupervisor(TaskStore(Path(path)), owner_active=lambda owner: True)
    try:
        output.put("ready")
        assert gate.wait(15)
        output.put(supervisor.recover())
    finally:
        supervisor.close()


def test_two_recovery_processes_do_not_double_requeue(store, supervisor):
    record, _, owner, attempt = _claim(store, supervisor, ready=True)
    owner.close()
    attempt.close()
    context = multiprocessing.get_context("spawn")
    gate, output = context.Event(), context.Queue()
    children = [
        context.Process(target=_recover_racer, args=(str(store.path), gate, output))
        for _ in range(2)
    ]
    try:
        for child in children:
            child.start()
        assert [output.get(timeout=15) for _ in children] == ["ready", "ready"]
        gate.set()
        assert sum(output.get(timeout=15) for _ in children) == 1
        for child in children:
            child.join(5)
            assert child.exitcode == 0
        assert store.get("alice", record["task_id"])["recovery_count"] == 1
    finally:
        for child in children:
            if child.is_alive():
                child.kill()
            child.join(5)
        output.close()
        output.join_thread()


@pytest.mark.parametrize("corruption", ["symlink", "permissions", "hardlink"])
def test_guard_refuses_unsafe_files(tmp_path, corruption):
    path = guard_path(tmp_path / "test.db", "owner")
    guard = TaskGuard.acquire(path, create=True)
    guard.close()
    if corruption == "symlink":
        renamed = path.with_suffix(".old")
        path.rename(renamed)
        path.symlink_to(renamed)
    elif corruption == "permissions":
        path.chmod(0o644)
    else:
        os.link(path, path.with_suffix(".link"))
    with pytest.raises((OSError, UnsafeTaskGuard)):
        TaskGuard.acquire(path)


def test_inherited_fd_rejects_wrong_inode(tmp_path):
    first, second = [guard_path(tmp_path / "db", name) for name in ("one", "two")]
    a, b = TaskGuard.acquire(first, create=True), TaskGuard.acquire(second, create=True)
    try:
        with pytest.raises(UnsafeTaskGuard):
            verify_inherited_guard(a.fd, second)
    finally:
        a.close()
        b.close()


def test_unlocked_fd_is_not_inherited_execution_proof(tmp_path):
    path = guard_path(tmp_path / "db", "owner")
    guard = TaskGuard.acquire(path, create=True)
    guard.close()
    fd = os.open(path, os.O_RDWR)
    try:
        with pytest.raises(UnsafeTaskGuard, match="没有继承"):
            verify_inherited_guard(fd, path)
    finally:
        os.close(fd)


@pytest.mark.parametrize("corruption", ["symlink", "permissions"])
def test_guard_refuses_unsafe_directory(tmp_path, corruption):
    path = guard_path(tmp_path / "db", "owner")
    if corruption == "symlink":
        actual = tmp_path / "other"
        actual.mkdir(mode=0o700)
        path.parent.symlink_to(actual, target_is_directory=True)
    else:
        path.parent.mkdir(mode=0o755)
        path.parent.chmod(0o755)
    with pytest.raises(UnsafeTaskGuard):
        TaskGuard.acquire(path, create=True)


def test_alias_database_uses_same_guard_namespace(store, tmp_path):
    alias = tmp_path / "alias.db"
    alias.symlink_to(store.path)
    assert guard_path(alias, "owner") == guard_path(store.path, "owner")
