"""回测 CLI 命令。"""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any

import click

from easy_tdx.backtest.cli_data import load_cli_frame
from easy_tdx.backtest.reporting import metric_text, metrics_csv, strict_json


@click.command()
@click.argument("market")
@click.argument("code")
@click.option("--strategy", "strategy_str", default=None, help="DSL 策略表达式 (P1)")
@click.option("--strategy-file", "strategy_file", default=None, help="Python 策略文件路径")
@click.option(
    "--combo-strategies",
    "combo_strategies",
    default=None,
    help="多因子组合：逗号分隔的策略文件路径（如 strats/a.py,strats/b.py,strats/c.py）",
)
@click.option(
    "--combo-mode",
    "combo_mode",
    default="MAJORITY",
    type=click.Choice(["AND", "OR", "MAJORITY"], case_sensitive=False),
    help="多因子信号合并模式（默认 MAJORITY）",
)
@click.option("--cash", default=100000.0, type=float, help="初始资金")
@click.option("--commission", default=0.0003, type=float, help="佣金率")
@click.option(
    "--execution",
    default="next_open",
    type=click.Choice(["next_open", "next_close"]),
    help="成交价规则",
)
@click.option("--period", default="DAILY", help="K线周期")
@click.option("--adjust", default="NONE", help="复权: NONE/QFQ/HFQ")
@click.option("--count", default=500, type=int, help="K线数量")
@click.option("--indicators", default=None, help="预计算指标（逗号分隔）")
@click.option(
    "--chanlun-level",
    "chanlun_level",
    default=None,
    help="自动计算缠论分析并注入策略（如 DAILY/30MIN）",
)
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option(
    "--output",
    "output_fmt",
    type=click.Choice(["json", "table", "csv"]),
    default="json",
    help="json 为完整结果；csv 为带状态与原因的绩效指标表",
)
def backtest(
    market: str,
    code: str,
    strategy_str: str | None,
    strategy_file: str | None,
    combo_strategies: str | None,
    combo_mode: str,
    cash: float,
    commission: float,
    execution: str,
    period: str,
    adjust: str,
    count: int,
    indicators: str | None,
    chanlun_level: str | None,
    use_table: bool,
    output_fmt: str,
) -> None:
    """回测引擎：执行策略并返回绩效报告。

    示例：

      easy-tdx backtest SZ 000001 --strategy-file my_strategy.py

      easy-tdx backtest SH 600519 --strategy-file ma_cross.py --table

      easy-tdx backtest SZ 000001 --strategy-file my_strategy.py --indicators MACD,KDJ

      easy-tdx backtest SZ 000001 --strategy-file chanlun_strategy.py --chanlun-level DAILY

      easy-tdx backtest SZ 000001 \
        --combo-strategies strategies/macd_cross.py,strategies/rsi_reversal.py \
        --combo-mode MAJORITY --table
    """
    from ..backtest.engine import BacktestEngine
    from ..cli.conn import get_mac_client
    from ..cli.parsers import parse_adjust, parse_market, parse_period
    from ..indicator import compute_indicators

    # 1. 加载策略（单策略 or 多因子组合）
    is_combo = combo_strategies is not None

    if is_combo:
        assert combo_strategies is not None  # narrowed by is_combo
        combo_classes = _load_combo_strategies(combo_strategies)
    else:
        strategy_cls = _load_strategy(strategy_str, strategy_file)
        if strategy_cls is None:
            click.echo("错误: 必须指定 --strategy-file / --combo-strategies / --strategy", err=True)
            raise SystemExit(1)

    # 2. 获取数据
    mkt = parse_market(market)
    with get_mac_client() as client:
        try:
            df = load_cli_frame(
                client, mkt, code, parse_period(period), parse_adjust(adjust), count
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    # 3. 预计算指标
    if indicators:
        indicator_list = [ind.strip() for ind in indicators.split(",")]
        metadata = deepcopy(df.attrs)
        df = compute_indicators(df, indicator_list)
        df.attrs = metadata

    # 4. 创建引擎并运行
    if is_combo:
        from ..backtest.combo import CombinationRunner

        runner = CombinationRunner(
            strategy_classes=combo_classes,
            df=df,
            cash=cash,
            commission=commission,
            execution=execution,
        )
        result = runner.run_combination(
            indices=list(range(len(combo_classes))),
            mode=combo_mode.upper(),
        )
    else:
        assert strategy_cls is not None  # guarded above by SystemExit
        engine = BacktestEngine(
            strategy=strategy_cls,
            cash=cash,
            commission=commission,
            execution=execution,
            chanlun_level=chanlun_level,
        )
        result = engine.run(df)

    # 5. 输出结果
    fmt = "table" if use_table else output_fmt
    if fmt == "json":
        click.echo(result.to_json())
    elif fmt == "table":
        _print_table(result)
    else:
        click.echo(
            metrics_csv(
                [("single", result.performance, result.config.get("performance_basis", {}))]
            ),
            nl=False,
        )


def _load_strategy(strategy_str: str | None, strategy_file: str | None) -> type | None:
    """加载策略类。

    优先从 Python 文件加载，其次从 DSL 表达式加载（未实现）。

    Args:
        strategy_str: DSL 策略表达式
        strategy_file: Python 策略文件路径

    Returns:
        Strategy 子类
    """

    if strategy_file:
        return _load_strategy_from_file(strategy_file)

    if strategy_str:
        click.echo("错误: DSL 策略表达式尚未实现", err=True)
        return None

    return None


def _load_strategy_from_file(path: str) -> type:
    """从 Python 文件加载 Strategy 子类。

    Args:
        path: Python 文件路径

    Returns:
        Strategy 子类
    """
    from ..backtest.strategy import Strategy

    file_path = Path(path)
    if not file_path.exists():
        click.echo(f"错误: 文件不存在: {path}", err=True)
        raise SystemExit(1)

    spec = importlib.util.spec_from_file_location("strategy_module", file_path)
    if spec is None or spec.loader is None:
        click.echo(f"错误: 无法加载文件: {path}", err=True)
        raise SystemExit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 查找 Strategy 子类
    strategy_classes = []
    for name in dir(module):
        obj = getattr(module, name)
        try:
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                strategy_classes.append(obj)
        except TypeError:
            pass

    if not strategy_classes:
        click.echo(f"错误: 文件中未找到 Strategy 子类: {path}", err=True)
        raise SystemExit(1)

    if len(strategy_classes) > 1:
        click.echo(f"警告: 文件包含多个 Strategy 子类，使用第一个: {path}", err=True)

    return strategy_classes[0]


def _load_combo_strategies(combo_strategies: str) -> list[type]:
    """从逗号分隔的路径列表加载多个策略类。

    Args:
        combo_strategies: 逗号分隔的策略文件路径

    Returns:
        Strategy 子类列表
    """
    paths = [p.strip() for p in combo_strategies.split(",") if p.strip()]
    if len(paths) < 2:
        click.echo("错误: --combo-strategies 至少需要 2 个策略文件", err=True)
        raise SystemExit(1)

    classes: list[type] = []
    for p in paths:
        cls = _load_strategy_from_file(p)
        classes.append(cls)

    names = [c.__name__ for c in classes]
    click.echo(f"[*] 多因子组合 ({len(classes)} 因子): {' + '.join(names)}", err=True)
    return classes


def _print_table(result: Any) -> None:
    """以表格形式输出回测结果。"""
    perf = result.performance
    config = result.config

    click.echo("=== 回测绩效概要 ===")
    click.echo(f"总收益率: {metric_text(perf.get('total_return'), '.2%')}")
    click.echo(f"年化收益: {metric_text(perf.get('annual_return'), '.2%')}")
    click.echo(f"最大回撤: {metric_text(perf.get('max_drawdown'), '.2%')}")
    click.echo(f"夏普比率: {metric_text(perf.get('sharpe'))}")
    click.echo(f"胜率: {metric_text(perf.get('win_rate'), '.2%')}")
    click.echo(f"交易次数: {metric_text(perf.get('total_trades'), '.0f')}")
    _print_basis(config.get("performance_basis", {}))
    click.echo()

    if getattr(result, "diagnostic", None):
        click.echo(f"⚠ 诊断: {result.diagnostic}")
        click.echo()

    click.echo("=== 配置参数 ===")
    click.echo(f"初始资金: {config.get('cash', 0):.2f}")
    click.echo(f"佣金率: {config.get('commission', 0):.4f}")
    click.echo(f"成交规则: {config.get('execution', 'next_open')}")
    if config.get("chanlun_level"):
        click.echo(f"缠论级别: {config.get('chanlun_level')}")
    click.echo()

    if config.get("future_leak_warning"):
        click.echo("!!! 警告: 策略可能存在未来函数（使用未来数据）")
        click.echo()

    if not result.trades.empty:
        click.echo("=== 最近交易记录 ===")
        recent_trades = result.trades.tail(10)
        for idx, trade in recent_trades.iterrows():
            direction = "买入" if trade["direction"] == "BUY" else "卖出"
            status = "拒绝" if trade["rejected"] else "成交"
            click.echo(
                f"  [{trade['datetime']}] {direction} "
                f"数量={trade['size']:.0f} 价格={trade['price']:.2f} "
                f"盈亏={trade['pnl']:.2f} [{status}]"
            )
    else:
        click.echo("无交易记录")


# ── portfolio 多标的组合回测命令 ─────────────────────────────────────────────


@click.command()
@click.option(
    "--stocks",
    required=True,
    help="股票列表：逗号分隔的 市场:代码（如 SZ:000001,SH:600519,SH:600036）",
)
@click.option("--strategy-file", "strategy_file", required=True, help="Python 策略文件路径")
@click.option("--cash", default=200_000.0, type=float, help="总资金（默认 20 万）")
@click.option("--commission", default=0.0003, type=float, help="佣金率")
@click.option(
    "--execution",
    default="next_open",
    type=click.Choice(["next_open", "next_close"]),
    help="成交价规则",
)
@click.option("--period", default="DAILY", help="K线周期")
@click.option("--adjust", default="NONE", help="复权: NONE/QFQ/HFQ")
@click.option("--count", default=500, type=int, help="K线数量")
@click.option(
    "--allocation",
    default="equal",
    type=click.Choice(["equal"], case_sensitive=False),
    help="资金分配方式（默认 equal 均等分配）",
)
@click.option(
    "--chanlun-level",
    "chanlun_level",
    default=None,
    help="自动计算缠论分析并注入策略（如 DAILY/30MIN）",
)
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option(
    "--output",
    "output_fmt",
    type=click.Choice(["json", "table", "csv"]),
    default="json",
    help="json 为完整结果；csv 为组合及各标的带状态与原因的绩效指标表",
)
def portfolio(
    stocks: str,
    strategy_file: str,
    cash: float,
    commission: float,
    execution: str,
    period: str,
    adjust: str,
    count: int,
    allocation: str,
    chanlun_level: str | None,
    use_table: bool,
    output_fmt: str,
) -> None:
    """多标的组合回测：共享资金池，独立产生信号，统一管理仓位。

    对多只股票同时回测，按均等比例分配资金，汇总组合整体绩效。

    示例：

      easy-tdx portfolio --stocks SZ:000001,SH:600519 --strategy-file ma_cross.py

      easy-tdx portfolio --stocks SZ:000001,SH:600519,SH:600036 \\
        --strategy-file my_strategy.py --cash 500000 --table

      easy-tdx portfolio --stocks SZ:000001,SH:600519 \\
        --strategy-file chanlun_strat.py --chanlun-level DAILY
    """
    from ..cli.conn import get_mac_client
    from ..cli.parsers import parse_adjust, parse_market, parse_period
    from .portfolio_engine import PortfolioBacktestEngine, StockData

    # 1. 加载策略
    strategy_cls = _load_strategy_from_file(strategy_file)
    strategy_name = strategy_cls.__name__

    # 2. 解析股票列表
    stock_list = []
    for item in stocks.split(","):
        item = item.strip()
        if ":" not in item:
            click.echo(f"错误: 股票格式应为 市场:代码，如 SZ:000001，收到: {item}", err=True)
            raise SystemExit(1)
        mkt_str, code = item.split(":", 1)
        stock_list.append((mkt_str.strip().upper(), code.strip()))

    if not stock_list:
        click.echo("错误: 未指定股票", err=True)
        raise SystemExit(1)

    click.echo(f"策略: {strategy_name} | 标的: {len(stock_list)} 只 | 资金: {cash:,.0f}", err=True)

    # 3. 获取数据
    stock_data_list: list[StockData] = []
    with get_mac_client() as client:
        for mkt_str, code in stock_list:
            mkt = parse_market(mkt_str)
            try:
                df = load_cli_frame(
                    client, mkt, code, parse_period(period), parse_adjust(adjust), count
                )
            except ValueError as exc:
                raise click.ClickException(f"{mkt_str}:{code}：{exc}；组合未执行") from exc
            stock_data_list.append(StockData(code=code, market=mkt_str, df=df))

    # 4. 创建引擎并运行
    engine = PortfolioBacktestEngine(
        strategy=strategy_cls,
        stocks=stock_data_list,
        total_cash=cash,
        allocation=allocation,
        commission=commission,
        execution=execution,
        chanlun_level=chanlun_level,
    )
    result = engine.run()

    # 5. 输出结果
    fmt = "table" if use_table else output_fmt
    if fmt == "table":
        _print_portfolio_table(result)
    elif fmt == "csv":
        groups = [("portfolio", result.total_performance, result.performance_basis)]
        groups.extend(
            (key, item.performance, item.config.get("performance_basis", {}))
            for key, item in result.individual_results.items()
        )
        click.echo(metrics_csv(groups), nl=False)
    else:
        click.echo(strict_json(result.to_dict()))


def _print_portfolio_table(result: Any) -> None:
    """以表格形式输出组合回测结果。"""
    perf = result.total_performance

    click.echo("=== 组合回测绩效概要 ===")
    click.echo(f"标的数量: {perf.get('total_stocks', 0)}")
    click.echo(f"总资金: {perf.get('total_cash', 0):,.0f}")
    click.echo(f"组合收益率: {metric_text(perf.get('total_return'), '.2%')}")
    click.echo(f"组合年化: {metric_text(perf.get('annual_return'), '.2%')}")
    _print_basis(result.performance_basis)
    click.echo()

    click.echo("── 各标的详情 ──")
    for key, stock_result in result.individual_results.items():
        sp = stock_result.performance
        alloc = result.equity_allocation.get(key, 0)
        click.echo(
            f"  {key}: 收益={metric_text(sp.get('total_return'), '.2%')} "
            f"夏普={metric_text(sp.get('sharpe'))} "
            f"回撤={metric_text(sp.get('max_drawdown'), '.2%')} "
            f"分配={alloc:.0%} "
            f"交易={sp.get('total_trades', 0)}"
        )
    click.echo()


def _print_basis(basis: dict[str, Any]) -> None:
    if not basis:
        click.echo("绩效口径：历史结果未记录，不能视为已核验")
        return
    click.echo(
        f"绩效采样：{basis.get('input_category')} → {basis.get('sample_category')}；"
        f"{basis.get('return_count')} 个收益样本；{basis.get('contract_version')}"
    )
    for warning in basis.get("warnings", []):
        click.echo(f"提示：{warning}")
    if basis.get("unavailable_reason"):
        click.echo(f"年化不可用：{basis['unavailable_reason']}")
    for key, state in basis.get("metric_status", {}).items():
        if state["state"] != "finite":
            click.echo(f"  {key}：{state['reason']}")
