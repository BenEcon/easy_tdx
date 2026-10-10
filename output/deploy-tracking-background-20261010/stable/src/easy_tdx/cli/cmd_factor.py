"""因子 CLI 命令。"""

from __future__ import annotations

import json

import click


@click.group("factor")
def factor() -> None:
    """因子研究工具。"""
    pass


@factor.command("list")
@click.option(
    "--category",
    default=None,
    help="按类别筛选: momentum/volatility/quality/volume/technical/chanlun/value",
)
@click.option("--table", "use_table", is_flag=True, help="表格输出")
def factor_list(category: str | None, use_table: bool) -> None:
    """列出所有已注册的因子。

    示例：

      easy-tdx factor list

      easy-tdx factor list --category momentum --table
    """
    from easy_tdx.factor.builtin import list_factors

    factors = list_factors()

    if category:
        factors = [f for f in factors if f["category"] == category]

    if use_table:
        try:
            from tabulate import tabulate

            rows = [
                {
                    "name": f["name"],
                    "category": f["category"],
                    "description": f["description"],
                }
                for f in factors
            ]
            click.echo(tabulate(rows, headers="keys", tablefmt="grid"))
        except ImportError:
            for f in factors:
                click.echo(f"{f['name']}\t{f['category']}\t{f['description']}")
    else:
        click.echo(json.dumps(factors, ensure_ascii=False, indent=2))


@factor.command("analyze")
@click.argument("factor_name")
@click.option("--period", default=5, type=int, help="远期收益天数")
@click.option("--n-quantiles", default=5, type=int, help="分层数")
def factor_analyze(factor_name: str, period: int, n_quantiles: int) -> None:
    """分析指定因子的有效性。

    示例：

      easy-tdx factor analyze momentum_20d

      easy-tdx factor analyze rsi_14 --period 10 --n-quantiles 10
    """
    click.echo(
        json.dumps(
            {
                "message": "factor analyze 需要行情数据，请使用 Python API",
                "factor": factor_name,
                "example": (
                    f"from easy_tdx.factor import FactorEngine, FactorAnalyzer, preprocess\n"
                    f"engine = FactorEngine()\n"
                    f"factor_data = engine.compute_cross_section(data, ['{factor_name}'])\n"
                    f"clean = preprocess(factor_data, ['{factor_name}'])\n"
                    f"return_data = engine.compute_forward_returns(data, period={period})\n"
                    f"analyzer = FactorAnalyzer(clean, return_data, n_quantiles={n_quantiles})\n"
                    f"report = analyzer.full_report()\n"
                    f"print(f'IC={{report.ic_mean:.3f}}, IR={{report.ir:.3f}}')"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
