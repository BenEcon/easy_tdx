"""Algorithm checkpoint invariants, independent of database/worker machinery."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.optimizer import ParamGridOptimizer
from easy_tdx.checkpoints import calculation_journal, checkpoint_scope


class Journal:
    def __init__(self, fail_at=None):
        self.state = None
        self.fail_at = fail_at

    def restore(self, key):
        return deepcopy(self.state)

    def save(self, key, state):
        if self.fail_at == len(state["points"]):
            raise OSError("checkpoint write failure")
        self.state = deepcopy(state)

    def used(self, key, completed):
        assert completed == len(self.state["points"])


def optimizer():
    return ParamGridOptimizer("ma_cross", {"fast": [2, 5, 5], "slow": [5, 10]}, pd.DataFrame())


def test_storage_failure_not_swallowed_as_failed_grid_point(monkeypatch):
    calls = []

    def run(*args):
        calls.append(True)
        return SimpleNamespace(performance={"total_return": 0.12345678901234567}, config={})

    monkeypatch.setattr(BacktestEngine, "run", run)
    journal = Journal(fail_at=2)
    with checkpoint_scope(journal), pytest.raises(OSError, match="checkpoint write"):
        optimizer().run()
    assert len(journal.state["points"]) == 1 and len(calls) == 2
    journal.fail_at = None
    calls.clear()
    with checkpoint_scope(journal):
        resumed = optimizer().run().to_dict()
    assert len(calls) == 3  # rerun the uncommitted second point, not the first
    assert resumed == optimizer().run().to_dict()
    assert calculation_journal() is None


def test_failed_and_invalid_points_are_not_retried_or_counted_as_success(monkeypatch):
    calls = []

    def run(*args):
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError("synthetic per-point failure")
        return SimpleNamespace(
            performance={"profit_factor": float("inf"), "sharpe": np.float32(0.3)}, config={}
        )

    monkeypatch.setattr(BacktestEngine, "run", run)
    journal = Journal()
    with checkpoint_scope(journal):
        original = optimizer().run().to_dict()
    assert [p["status"] for p in journal.state["points"]] == [
        "ok",
        "failed",
        "invalid",
        "ok",
        "invalid",
        "ok",
    ]
    assert np.isposinf(journal.state["points"][0]["result"]["profit_factor"])
    assert journal.state["points"][0]["result"]["sharpe"].dtype == np.dtype("float32")
    calls.clear()
    with checkpoint_scope(journal):
        resumed = optimizer().run().to_dict()
    assert not calls and resumed == original


@pytest.mark.parametrize(
    "damage",
    ["schema", "total", "order", "result", "status", "unknown", "metric_state", "calendar"],
)
def test_malformed_algorithm_state_rejected_before_new_computation(monkeypatch, damage):
    monkeypatch.setattr(
        BacktestEngine, "run", lambda *args: SimpleNamespace(performance={}, config={})
    )
    journal = Journal()
    with checkpoint_scope(journal):
        optimizer().run()
    if damage == "schema":
        journal.state["schema"] = "other"
    elif damage == "calendar":
        journal.state["performance_contract"] = "performance-sampling-v4"
    elif damage == "metric_state":
        journal.state["points"][0]["result"]["metric_status"]["sharpe"]["state"] = "finite"
    elif damage == "total":
        journal.state["total"] = True
    elif damage == "order":
        journal.state["points"].reverse()
    elif damage == "result":
        del journal.state["points"][0]["result"]["sharpe"]
    elif damage == "status":
        journal.state["points"][0]["status"] = "invalid"
    else:
        journal.state["unrecognized"] = 1
    monkeypatch.setattr(
        BacktestEngine, "run", lambda *args: pytest.fail("must validate before compute")
    )
    with checkpoint_scope(journal), pytest.raises(ValueError, match="检查点|网格点"):
        optimizer().run()


def test_changed_cost_parameters_reject_previous_grid_state(monkeypatch):
    monkeypatch.setattr(
        BacktestEngine, "run", lambda *args: SimpleNamespace(performance={}, config={})
    )
    journal = Journal()
    with checkpoint_scope(journal):
        optimizer().run()
    changed = optimizer()
    changed._commission = 0.001
    with checkpoint_scope(journal), pytest.raises(ValueError, match="配置"):
        changed.run()
