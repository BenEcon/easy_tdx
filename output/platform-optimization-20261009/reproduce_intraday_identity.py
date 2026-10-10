"""Read-only synthetic reproduction: signals must not execute before their bar."""

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy


class TimedOrders(Strategy):
    def init(self):
        pass

    def next(self):
        if self._bar_index == 3:
            self.buy(size=100)
        if self._bar_index == 5:
            self.sell(size=100)


dates = pd.date_range("2026-10-09 09:35", periods=8, freq="5min")
frame = pd.DataFrame({
    "datetime": dates,
    "open": [20.0 + n for n in range(8)],
    "close": [20.2 + n for n in range(8)],
    "high": [21.0 + n for n in range(8)],
    "low": [19.0 + n for n in range(8)],
    "vol": [10000] * 8,
})
engine = BacktestEngine(TimedOrders, cash=100000, position_mode="fixed")
result = engine.run(frame)
print("Synthetic fixture, next_open, no network or production data")
print("Expected BUY: signal=09:50, execution=09:55, price=24")
print("Expected SELL: signal=10:00, execution=10:05, price=26")
print(result.trades.to_string(index=False))
print("Positions:")
print(result.positions.to_string(index=False))
actual_times = list(result.trades["datetime"])
if actual_times == [dates[4], dates[6]]:
    print("PASS: execution times match causal bar positions")
else:
    print("REPRODUCED: date-only signal matching chooses earlier intraday bars")
