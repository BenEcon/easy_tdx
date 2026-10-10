"""Observed progress is fenced, bounded, ephemeral per attempt, and not a result."""

import time
from threading import Event

import pytest

from easy_tdx.computation import ComputationStopped
from easy_tdx.progress import (
    ProgressPublicationError,
    progress_scope,
    report_progress,
    validate_progress,
)
from easy_tdx.web.task_dispatch import dispatch_task
from easy_tdx.web.task_runner import BacktestTaskRunner
from easy_tdx.web.task_store import StaleTaskLease, TaskStore
from tests.unit.test_factor_tasks import value as factor_task_fixture


@pytest.fixture
def value():
    return factor_task_fixture.__wrapped__()


def point(sequence=1, completed=0):
    return dict(
        phase="factor_values",
        completed=completed,
        total=5,
        detail="momentum_20d",
        sequence=sequence,
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"phase": "secret"},
        {"completed": True},
        {"completed": -1},
        {"completed": 6},
        {"total": 0},
        {"sequence": 0},
        {"sequence": 1.5},
        {"detail": "x" * 97},
        {"extra": 1},
    ],
)
def test_bad_progress_is_rejected_without_coercion(patch):
    with pytest.raises(ValueError):
        validate_progress({**point(), **patch})


def test_nested_scope_restores_and_does_not_leak():
    outer, inner = [], []
    with progress_scope(outer.append):
        report_progress("archive", 0, 2)
        with progress_scope(inner.append):
            report_progress("archive", 1, 2)
        report_progress("archive", 2, 2)
    report_progress("archive", 0, 2)
    assert [p["sequence"] for p in outer] == [1, 2]
    assert [p["sequence"] for p in inner] == [1]


def test_real_factor_work_emits_exact_completed_units_without_changing_results(value):
    expected = dispatch_task(value)
    events = []
    with progress_scope(events.append):
        actual = dispatch_task(value)
    assert actual == expected
    assert [p["sequence"] for p in events] == list(range(1, len(events) + 1))
    phases = {key: [p for p in events if p["phase"] == key] for key in {p["phase"] for p in events}}
    assert [p["completed"] for p in phases["factor_values"]] == list(range(6))
    assert [p["completed"] for p in phases["factor_windows"]] == list(range(5))
    assert [p["completed"] for p in phases["redundancy"]] == [0, 1]
    assert [p["completed"] for p in phases["time_validation"]] == list(range(5))
    assert [p["completed"] for p in phases["archive"]] == list(range(6))
    assert [p["completed"] for p in phases["result_validation"]] == [0, 1]
    assert "progress" not in actual  # Metadata never changes saved numerical results.


def test_progress_sink_loss_inside_factor_loop_is_not_converted_to_factor_missing(value):
    def broken(p):
        if p["completed"] == 1:
            raise OSError("lost task store")

    with progress_scope(broken), pytest.raises(ProgressPublicationError, match="lost task store"):
        dispatch_task(value)


def test_durable_progress_survives_reopen_but_not_attempt_recovery(value, tmp_path):
    store = TaskStore(tmp_path / "tasks.db")
    job, _ = store.submit("alice", value)
    lease = store.claim(value.execution_version, "worker")
    store.publish_progress(lease, point())
    assert TaskStore(store.path).get("alice", job["task_id"])["progress"] == point()
    assert store.list_tasks("alice")[0]["progress"] == point()
    with pytest.raises(KeyError):
        store.get("bob", job["task_id"])
    with pytest.raises(ValueError, match="过期"):
        store.publish_progress(lease, point())
    store.requeue_after_exit(lease)
    assert store.get("alice", job["task_id"])["progress"] is None
    fresh = store.claim(value.execution_version, "worker-2")
    with pytest.raises(StaleTaskLease):
        store.publish_progress(lease, point(2, 1))
    store.publish_progress(fresh, point())
    store.cancel("alice", job["task_id"])
    with pytest.raises(ComputationStopped):
        store.publish_progress(fresh, point(2, 1))
    assert store.get("alice", job["task_id"])["progress"] == point()
    store.finish_after_exit(fresh, error="worker stopped")
    assert store.get("alice", job["task_id"])["status"] == "cancelled"
    with pytest.raises(StaleTaskLease):
        store.publish_progress(fresh, point(2, 1))


def test_memory_live_progress_is_not_completion_and_stops_with_cancel():
    runner = BacktestTaskRunner(max_workers=1)
    reached, release = Event(), Event()

    def work():
        report_progress("result_validation", 1, 1)
        reached.set()
        release.wait(3)
        report_progress("archive", 1, 1)
        return {"partial": True}

    try:
        task = runner.submit(work, owner_id="alice", kind="factor_evaluation")
        assert reached.wait(2)
        state = runner.get(task)
        assert state.status == "running" and state.result is None
        assert state.kind == "factor_evaluation" and state.progress["completed"] == 1
        assert state.to_dict()["progress"] == state.progress
        runner.cancel(task)
        release.set()
        deadline = time.monotonic() + 3
        while runner.get(task).status == "cancelling" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.get(task).status == "cancelled"
        assert runner.get(task).progress["phase"] == "result_validation"
    finally:
        release.set()
        runner.shutdown()
