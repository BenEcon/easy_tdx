"""easy_tdx.backtest — 向量化策略回测引擎（纯计算，零网络依赖）。

快速开始::

    from easy_tdx.backtest import BacktestEngine, Strategy

    class MyStrategy(Strategy):
        def init(self):
            self.ma5 = self.I(MA, self.data.close, 5)
            self.ma20 = self.I(MA, self.data.close, 20)

        def next(self):
            if crossover(self.ma5, self.ma20):
                self.buy()
            elif crossover(self.ma20, self.ma5):
                self.sell()

    engine = BacktestEngine(strategy=MyStrategy, cash=100000)
    result = engine.run(df)
    print(result.performance)
"""

from easy_tdx.backtest.combo import CombinationRunner, ComboResult, FactorSignals  # noqa: F401
from easy_tdx.backtest.engine import BacktestEngine  # noqa: F401
from easy_tdx.backtest.strategy import Strategy, StrategyDataProxy, crossover  # noqa: F401
from easy_tdx.backtest.types import BacktestResult, Position, Signal, Trade  # noqa: F401

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "CombinationRunner",
    "ComboResult",
    "FactorSignals",
    "Strategy",
    "StrategyDataProxy",
    "Signal",
    "Trade",
    "Position",
    "crossover",
]
