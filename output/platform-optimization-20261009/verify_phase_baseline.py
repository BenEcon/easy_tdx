"""Compare this phase to the verified pre-change source archive, offline only."""
import importlib.util
import sys
from copy import deepcopy
from dataclasses import asdict
from itertools import product
from pathlib import Path
from time import perf_counter

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.slippage import FixedSlippage
from easy_tdx.backtest.strategies.builtin import MaCrossStrategy


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


root = Path(sys.argv[1]) / "src/easy_tdx/backtest"
old_orders = load("phase_old_orders", root / "orders.py").OrderSimulator
old_tracker = load("phase_old_portfolio", root / "portfolio.py").PortfolioTracker
old_engine = load("phase_old_engine", root / "engine.py").BacktestEngine
test = load("phase_test_cases", Path(__file__).resolve().parents[2] / "tests/unit/test_backtest_phase_checkpoints.py")
frame = test.data()
frame.index = pd.RangeIndex(100, 100 + len(frame))
cases = 0
matching_seconds = {"default": [0.0, 0.0], "custom": [0.0, 0.0]}
for execution, mode, reject, cash, slippage in product(
    ["next_open", "next_close"], ["full", "fixed", "percent"], ["reduce", "skip"],
    [100000, 100000.12345678901], [None, FixedSlippage(0.03)],
):
    signals = test.inputs(frame)
    if mode == "percent":
        for item in signals:
            item.size = 0.4
    options = dict(execution=execution, position_mode=mode, reject_policy=reject,
                   commission=0.0007, slippage=0.02, slippage_model=slippage)
    group = matching_seconds["default" if slippage is None else "custom"]
    started = perf_counter()
    old = old_orders(frame, **options).simulate(deepcopy(signals), cash, 100.0)
    group[0] += perf_counter() - started
    started = perf_counter()
    new = OrderSimulator(frame, **options).simulate(deepcopy(signals), cash, 100.0)
    group[1] += perf_counter() - started
    assert [asdict(t) for t in new] == [asdict(t) for t in old], options
    old = old_engine(MaCrossStrategy)._compute_pnls(old)
    new = BacktestEngine(MaCrossStrategy)._compute_pnls(new)
    assert [asdict(t) for t in new] == [asdict(t) for t in old], options
    previous, current = old_tracker(frame, cash), PortfolioTracker(frame, cash)
    previous.apply_trades(old)
    current.apply_trades(new)
    pd.testing.assert_frame_equal(current.equity_curve, previous.equity_curve, check_exact=True)
    pd.testing.assert_frame_equal(current.positions, previous.positions, check_exact=True)
    cases += 1
print(f"{cases} archived-source comparisons passed: trades, costs, equity and positions exact")
for name, (old_seconds, new_seconds) in matching_seconds.items():
    print(f"{name}: matching-only accumulated seconds, old={old_seconds:.6f}, new={new_seconds:.6f}")
