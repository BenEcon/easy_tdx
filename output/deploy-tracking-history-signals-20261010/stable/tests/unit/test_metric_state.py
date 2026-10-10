"""Finite zero, unavailable, infinity and rejected orders must remain distinct."""

import json

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.metric_state import CONTRACT, metric_states
from easy_tdx.backtest.optimizer import GridPointResult, OptimizeResult, ParamGridOptimizer
from easy_tdx.backtest.performance import PerformanceAnalyzer
from easy_tdx.backtest.types import BacktestResult
from easy_tdx.web.backtest_schemas import serialize_result


def curve(values=(100.0, 101.0, 103.0, 102.0)):
    total = np.array(values)
    peak = np.maximum.accumulate(total)
    return pd.DataFrame(
        {
            "datetime": np.arange(len(total)),
            "total": total,
            "drawdown": peak - total,
            "drawdown_pct": (peak - total) / peak,
        }
    )


def trades(pnls=(), rejected=()):
    return pd.DataFrame(
        {
            "direction": ["SELL"] * len(pnls),
            "pnl": pnls,
            "cost_basis": [100.0] * len(pnls),
            "rejected": rejected or [False] * len(pnls),
        }
    )


def analyze(frame=None, records=None, **kwargs):
    analyzer = PerformanceAnalyzer(
        curve() if frame is None else frame, trades() if records is None else records, **kwargs
    )
    return analyzer.compute(), analyzer


@pytest.mark.parametrize(
    "pnl,win,loss,flat,rate,factor",
    [
        ([10, -5, 0], 1, 1, 1, 1 / 3, 2),
        ([-10, -5], 0, 2, 0, 0, 0),
        ([10, 5], 2, 0, 0, 1, float("inf")),
        ([0, 0], 0, 0, 2, 0, float("nan")),
    ],
)
def test_filled_trade_metrics(pnl, win, loss, flat, rate, factor):
    metrics, analyzer = analyze(
        records=trades([*pnl, -10000, 10000, 0], [False] * len(pnl) + [True] * 3)
    )
    assert metrics["total_trades"] == len(pnl)
    assert metrics["rejected_trades"] == 3
    assert (metrics["win_trades"], metrics["lose_trades"], metrics["breakeven_trades"]) == (
        win,
        loss,
        flat,
    )
    assert metrics["win_rate"] == rate
    assert metrics["profit_factor"] == pytest.approx(factor, nan_ok=True)
    assert analyzer.basis["metric_contract"] == CONTRACT
    assert analyzer.basis["metric_status"] == metric_states(
        metrics, {key: state["reason"] for key, state in analyzer.basis["metric_status"].items()}
    )


def test_rejected_only_is_no_sample_not_zero_win_rate():
    metrics, analyzer = analyze(records=trades([-30], [True]))
    assert metrics["total_trades"] == 0
    assert np.isnan(metrics["win_rate"])
    assert analyzer.basis["metric_status"]["win_rate"]["reason"]


def test_flat_curve_keeps_true_zeros_not_fake_ratios():
    metrics, analyzer = analyze(curve([100.0, 100.0, 100.0]), risk_free_rate=0)
    for key in ("total_return", "annual_return", "volatility", "max_drawdown", "max_dd_duration"):
        assert metrics[key] == 0
        assert analyzer.basis["metric_status"][key]["state"] == "finite"
    for key in ("sharpe", "sortino", "calmar", "win_rate", "profit_factor"):
        assert np.isnan(metrics[key])
        assert analyzer.basis["metric_status"][key]["state"] == "unavailable"


def test_monotonic_gains_have_explicit_infinity_not_sentinel():
    metrics, analyzer = analyze(curve([100.0, 101.0, 103.0, 107.0]))
    for key in ("sortino", "calmar"):
        assert np.isposinf(metrics[key])
        assert analyzer.basis["metric_status"][key]["state"] == "positive_infinity"
    assert analyzer.basis["sortino_definition"] == "negative_excess_return_population_std"


def test_real_999_is_preserved_as_finite():
    metrics, analyzer = analyze(records=trades([999.0, -1.0]))
    assert metrics["profit_factor"] == 999
    assert analyzer.basis["metric_status"]["profit_factor"]["state"] == "finite"


def test_invalid_pnl_and_partial_missing_cost_are_not_silently_dropped():
    frame = trades([10.0, 20.0])
    frame.loc[1, "cost_basis"] = np.nan
    metrics, _ = analyze(records=frame)
    assert np.isnan(metrics["avg_win"]) and np.isnan(metrics["max_win"])
    frame.loc[1, "pnl"] = np.nan
    metrics, _ = analyze(records=frame)
    assert metrics["total_trades"] == 2
    for key in ("win_rate", "profit_factor", "win_trades", "lose_trades"):
        assert np.isnan(metrics[key])


def test_json_roundtrip_retains_state_without_nonstandard_json_literals():
    metrics, analyzer = analyze(records=trades([10.0]))
    result = BacktestResult(
        metrics, curve(), trades([10.0]), pd.DataFrame(), {"performance_basis": analyzer.basis}
    )
    direct = json.loads(result.to_json(), parse_constant=lambda value: pytest.fail(value))
    web = serialize_result(result)
    for response in (direct, web):
        assert response["performance"]["profit_factor"] is None
        assert response["performance"]["avg_loss"] is None
        states = response["config"]["performance_basis"]["metric_status"]
        assert states["profit_factor"]["state"] == "positive_infinity"
        assert states["avg_loss"]["state"] == "unavailable"


def test_optimizer_summary_and_heatmap_preserve_null_and_state():
    point = GridPointResult({"fast": 2, "slow": 5}, profit_factor=float("inf"))
    opt = ParamGridOptimizer("ma_cross", {"fast": [2], "slow": [5]}, pd.DataFrame())
    heatmap = opt._build_heatmap([point], ["fast", "slow"])
    payload = OptimizeResult("ma_cross", ["fast", "slow"], [point], heatmap=heatmap).to_dict()
    json.dumps(payload, allow_nan=False)
    assert payload["heatmap"]["data"] == [[0, 0, None]]
    assert payload["results"][0]["metric_status"]["profit_factor"]["state"] == "positive_infinity"
    assert payload["best"] is None


def test_holding_slots_never_match_each_others_buys():
    frame = pd.DataFrame(
        {
            "direction": ["BUY", "SELL"],
            "pnl": [0.0, 10.0],
            "rejected": [False, False],
            "size": [100, 100],
            "datetime": [20261001, 20261003],
            "performance_slot": ["a", "b"],
        }
    )
    metrics, _ = analyze(records=frame)
    assert np.isnan(metrics["avg_holding_days"])
    frame["performance_slot"] = "a"
    metrics, _ = analyze(records=frame)
    assert metrics["avg_holding_days"] == 2
    frame["datetime"] = 20261001
    metrics, _ = analyze(records=frame)
    assert metrics["avg_holding_days"] == 0  # a real zero-day matched holding
    metrics, _ = analyze(records=frame.drop(columns=["size"]))
    assert np.isnan(metrics["avg_holding_days"])  # never invent 100-share lots
    frame.loc[1, "size"] = 200
    metrics, _ = analyze(records=frame)
    assert np.isnan(metrics["avg_holding_days"])  # partial pairing isn't full coverage


def test_optimizer_keeps_invalid_return_rows_but_never_selects_them_as_best(monkeypatch):
    from types import SimpleNamespace

    from easy_tdx.backtest.engine import BacktestEngine

    values = iter([float("nan"), -0.2, float("inf"), 0.1])
    monkeypatch.setattr(
        BacktestEngine,
        "run",
        lambda *args: SimpleNamespace(performance={"total_return": next(values)}, config={}),
    )
    opt = ParamGridOptimizer("ma_cross", {"fast": [2, 3, 4, 5], "slow": [10]}, pd.DataFrame())
    result = opt.run()
    assert len(result.results) == 4
    assert result.best.total_return == 0.1
    assert [r.total_return for r in result.results[:2]] == [0.1, -0.2]
    monkeypatch.setattr(
        BacktestEngine,
        "run",
        lambda *args: SimpleNamespace(performance={"total_return": float("nan")}, config={}),
    )
    result = opt.run()
    assert len(result.results) == 4 and result.best is None


def test_optimize_all_preserves_best_point_metric_status(monkeypatch):
    from easy_tdx.web.routers.backtest import _optimize_one_strategy

    point = GridPointResult({}, total_return=0.1, profit_factor=float("inf"))
    monkeypatch.setattr(
        ParamGridOptimizer, "run", lambda self: OptimizeResult("ma_cross", [], [point], best=point)
    )
    result = _optimize_one_strategy(
        "ma_cross", {"fast": [2]}, pd.DataFrame(), 100000.0, 0.0003, 0.0, "next_open"
    )
    response = serialize_result(result)
    assert response["profit_factor"] is None
    assert response["metric_status"]["profit_factor"]["state"] == "positive_infinity"
