"""组合因子选股 CLI 命令。"""

from __future__ import annotations

import json

import click


@click.group("pfactor")
def pfactor() -> None:
    """组合因子选股工具。"""
    pass


@pfactor.command("backtest")
@click.argument("factor_name")
@click.option("--n-stocks", default=50, type=int, help="持仓数量")
@click.option("--rebalance-freq", default="M", help="调仓频率: W/M/Q")
@click.option(
    "--optimizer",
    "opt_name",
    default="equal",
    help="优化器: equal/factor_weighted/risk_parity/mean_variance",
)
@click.option("--cash", default=1000000.0, type=float, help="初始资金")
def pfactor_backtest(
    factor_name: str, n_stocks: int, rebalance_freq: str, opt_name: str, cash: float
) -> None:
    """运行组合因子回测。

    示例：

      easy-tdx pfactor backtest momentum_20d

      easy-tdx pfactor backtest rsi_14 --n-stocks 10 --optimizer factor_weighted
    """
    click.echo(
        json.dumps(
            {
                "message": "pfactor backtest 需要行情数据，请使用 Python API",
                "example": (
                    f"from easy_tdx.portfolio import RebalanceEngine, EqualWeightOptimizer\n"
                    f"engine = RebalanceEngine(\n"
                    f"    optimizer=EqualWeightOptimizer(),\n"
                    f"    factor_name='{factor_name}',\n"
                    f"    n_stocks={n_stocks},\n"
                    f"    rebalance_freq='{rebalance_freq}',\n"
                    f"    cash={cash},\n"
                    f")\n"
                    f"result = engine.run(data, start_date=20230101, end_date=20240101)\n"
                    f"print(f'年化收益={{result.performance[\"annual_return\"]:.2%}}')"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
