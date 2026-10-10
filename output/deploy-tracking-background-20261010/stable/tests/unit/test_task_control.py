"""Backpressure and cancellation must describe real worker state, never UI intent."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from easy_tdx.computation import (
    ComputationControl,
    ComputationStopped,
    computation_checkpoint,
    computation_scope,
)
from easy_tdx.web.task_runner import BacktestTaskRunner, TaskCapacityError


def wait_terminal(runner, task_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = runner.get(task_id)
        if state.status not in {"pending", "running", "cancelling"}:
            return state
        time.sleep(0.005)
    pytest.fail("worker did not exit")


@pytest.mark.parametrize(
    "options",
    [
        {"max_task_seconds": float("nan")},
        {"max_task_seconds": float("inf")},
        {"max_task_seconds": 0},
        {"max_active": 0},
        {"max_active": 1.5},
        {"max_per_owner": True},
        {"max_results": -1},
        {"max_workers": 0},
    ],
)
def test_invalid_quota(options):
    with pytest.raises(ValueError):
        BacktestTaskRunner(**options)


def test_queue_cancellation_frees_slot_without_executing():
    runner = BacktestTaskRunner(max_workers=1, max_active=2, max_per_owner=2)
    started, release, called = Event(), Event(), Event()

    def slow():
        started.set()
        release.wait(3)
        return {"ok": True}

    try:
        first = runner.submit(slow, owner_id="a")
        assert started.wait(1)
        second = runner.submit(lambda: called.set() or {}, owner_id="a")
        with pytest.raises(TaskCapacityError):
            runner.submit(lambda: {}, owner_id="b")
        assert runner.cancel(second).status == "cancelled"
        replacement = runner.submit(lambda: {}, owner_id="b")
        assert runner.get(first).status == "running"
        assert runner.get(replacement).status == "pending"
    finally:
        release.set()
        runner.shutdown()
    assert not called.is_set()


@pytest.mark.parametrize("raises", [False, True])
def test_running_cancel_retains_slot_and_drops_late_result_or_error(raises):
    runner = BacktestTaskRunner(max_workers=1, max_active=1)
    started, release = Event(), Event()

    def slow():
        started.set()
        release.wait(3)
        if raises:
            raise ValueError("late native failure")
        return {"must_not_publish": True}

    try:
        task = runner.submit(slow, owner_id="a")
        assert started.wait(1)
        assert runner.cancel(task).status == "cancelling"
        with pytest.raises(TaskCapacityError):
            runner.submit(lambda: {}, owner_id="b")
        release.set()
        state = wait_terminal(runner, task)
        assert state.status == "cancelled" and state.result is None
        assert state.error == "任务已取消"
        assert wait_terminal(runner, runner.submit(lambda: {"ok": True})).status == "done"
    finally:
        release.set()
        runner.shutdown()


def test_deadline_requests_cancellation_but_does_not_free_running_slot():
    runner = BacktestTaskRunner(max_workers=1, max_active=1, max_task_seconds=0.02)
    started, release = Event(), Event()

    def slow():
        started.set()
        release.wait(3)
        return {"partial": 1}

    try:
        task = runner.submit(slow)
        assert started.wait(1)
        time.sleep(0.03)
        assert runner.get(task).status == "cancelling"
        with pytest.raises(TaskCapacityError):
            runner.submit(lambda: {})
        runner.cancel(task)  # The first stop cause (deadline) must be retained.
        release.set()
        state = wait_terminal(runner, task)
        assert state.status == "timed_out" and state.result is None
    finally:
        release.set()
        runner.shutdown()


def test_concurrent_per_owner_admission_is_atomic():
    runner = BacktestTaskRunner(max_workers=1, max_active=16, max_per_owner=3)
    release = Event()

    def submit(_):
        try:
            return runner.submit(lambda: release.wait(3) or {}, owner_id="same")
        except TaskCapacityError:
            return None

    try:
        with ThreadPoolExecutor(max_workers=12) as clients:
            submitted = list(clients.map(submit, range(12)))
        assert sum(t is not None for t in submitted) == 3
        other = runner.submit(lambda: {}, owner_id="other")
        assert runner.get(other).status == "pending"
    finally:
        release.set()
        runner.shutdown()


def test_checkpoint_bypasses_recoverable_strategy_errors_and_resets_context():
    control = ComputationControl()
    recovered = []
    with pytest.raises(ComputationStopped) as error:
        with computation_scope(control):
            control.request()
            try:
                computation_checkpoint()
            except Exception:
                recovered.append("partial-ranking")
    assert error.value.reason == "cancelled"
    assert not recovered
    computation_checkpoint()  # No leaked cancellation outside the scoped job.


def test_engine_stops_between_bars_not_after_full_backtest():
    import pandas as pd

    from easy_tdx.backtest.engine import BacktestEngine
    from easy_tdx.backtest.strategy import Strategy

    control = ComputationControl()
    visits = []

    class CancellingStrategy(Strategy):
        def init(self):
            pass

        def next(self):
            visits.append(self._bar_index)
            if len(visits) == 3:
                control.request()

    frame = pd.DataFrame(
        dict(
            datetime=pd.date_range("2026-01-01", periods=20),
            open=10,
            high=11,
            low=9,
            close=10,
            vol=100,
        )
    )
    with pytest.raises(ComputationStopped), computation_scope(control):
        BacktestEngine(strategy=CancellingStrategy()).run(frame)
    assert len(visits) == 3


def test_optimizer_never_returns_partial_ranking_after_cancel(monkeypatch):
    import pandas as pd

    from easy_tdx.backtest.engine import BacktestEngine
    from easy_tdx.backtest.optimizer import ParamGridOptimizer

    control = ComputationControl()
    original = BacktestEngine.run
    calls = []

    def run(engine, frame):
        calls.append(True)
        result = original(engine, frame)
        control.request()
        return result

    monkeypatch.setattr(BacktestEngine, "run", run)
    frame = pd.DataFrame(
        dict(
            datetime=pd.date_range("2026-01-01", periods=40),
            open=10,
            high=11,
            low=9,
            close=10,
            vol=100,
        )
    )
    optimizer = ParamGridOptimizer(
        strategy_name="ma_cross", param_grid={"fast": [5, 6], "slow": [20]}, df=frame
    )
    with pytest.raises(ComputationStopped), computation_scope(control):
        optimizer.run()
    assert len(calls) == 1


def test_shutdown_handles_queued_tasks_finishing_and_evicted_before_cancel(monkeypatch):
    runner = BacktestTaskRunner(max_workers=1, max_results=1)
    started, release = Event(), Event()

    def slow():
        started.set()
        release.wait(3)
        return {}

    runner.submit(slow)
    assert started.wait(1)
    runner.submit(lambda: {})
    runner.submit(lambda: {})
    original_cancel = runner.cancel
    observed_missing = []

    def interleaved_cancel(task_id):
        futures = list(runner._futures.values())
        release.set()
        for future in futures:
            future.result(2)
        observed_missing.append(runner.peek(task_id) is None)
        return original_cancel(task_id)

    monkeypatch.setattr(runner, "cancel", interleaved_cancel)
    try:
        runner.shutdown()
        assert any(observed_missing)  # Prove the formerly failing interleaving occurred.
        assert all(state.status == "done" for state in runner.list_recent())
    finally:
        release.set()
        runner._executor.shutdown()
