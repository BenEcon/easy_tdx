"""run-all 命令 — 批量运行 strategies/ 目录下所有策略并比较结果。

用法::

    easy-tdx run-all SZ 300308 --count 2000 --cash 1000000 --adjust QFQ

输出每个策略的绩效指标，并按总收益率排名。
"""

from __future__ import annotations

import importlib.util
import logging
import time
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)

# ── 辅助函数 ──────────────────────────────────────────────────────────────────


def _load_strategy_class(file_path: Path) -> type | None:
    """从 Python 文件加载 Strategy 子类，失败返回 None。"""
    from ..backtest.strategy import Strategy

    spec = importlib.util.spec_from_file_location("strategy_module", file_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # 策略文件可能有语法错误 / ImportError / 运行期异常，记录完整 traceback
        # 而非静默吞掉，否则用户只看到"加载失败"却不知根因（审计 #6）。
        logger.exception("策略文件加载失败: %s", file_path)
        return None

    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        try:
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                return obj
        except TypeError:
            pass

    return None


def _setup_chinese_font() -> None:
    """配置 matplotlib 中文字体，按平台自动选择。"""
    import platform

    import matplotlib

    system = platform.system()
    if system == "Windows":
        candidates = ["Microsoft YaHei", "SimHei", "KaiTi", "FangSong"]
    elif system == "Darwin":
        candidates = ["PingFang SC", "Heiti SC", "STHeiti"]
    else:
        candidates = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "Droid Sans Fallback"]

    import matplotlib.font_manager as fm

    available = {f.name for f in fm.fontManager.ttflist}
    for font in candidates:
        if font in available:
            matplotlib.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
            break
    matplotlib.rcParams["axes.unicode_minus"] = False


def _map_trade_values(trades_df: Any, equity: Any, initial_cash: float) -> list[float]:
    """将交易的 datetime 映射到 equity_curve 对应的归一化值。"""
    eq_dt = equity["datetime"].values
    eq_norm = equity["total"].values / initial_cash
    result_vals: list[float] = []
    for dt in trades_df["datetime"].values:
        idx = eq_dt.searchsorted(dt, side="right") - 1
        if idx < 0:
            idx = 0
        if idx >= len(eq_norm):
            idx = len(eq_norm) - 1
        result_vals.append(float(eq_norm[idx]))
    return result_vals


def _print_ranking(
    results: list[dict[str, Any]],
    backtest_results: dict[str, Any],
) -> bool:
    """输出策略绩效排名、综合评分和最佳策略明细。

    Returns:
        True 表示有有效结果，False 表示全部失败。
    """
    valid = [r for r in results if "error" not in r]
    errored = [r for r in results if "error" in r]

    if not valid:
        click.echo("所有策略均运行失败！")
        for r in errored:
            click.echo(f"  {r['strategy']}: {r['error']}")
        return False

    valid.sort(key=lambda x: x["total_return"], reverse=True)

    # ── 绩效排名 ──────────────────────────────────────────────────────────────
    click.echo("\n" + "=" * 80)
    click.echo("[*] 策略绩效排名 (按总收益率降序)")
    click.echo("=" * 80)

    click.echo(
        f"{'排名':>4}  {'策略':<22} {'总收益率':>10} {'年化收益':>10} "
        f"{'最大回撤':>10} {'夏普':>8} {'胜率':>8} {'交易次数':>8} {'盈亏比':>8}"
    )
    click.echo("-" * 100)

    for i, r in enumerate(valid, 1):
        medal = " *1*" if i == 1 else " *2*" if i == 2 else " *3*" if i == 3 else "    "
        click.echo(
            f"{medal}{i:>2}  {r['strategy']:<22} "
            f"{r['total_return']:>9.2%} "
            f"{r['annual_return']:>9.2%} "
            f"{r['max_drawdown']:>9.2%} "
            f"{r['sharpe']:>8.2f} "
            f"{r['win_rate']:>7.1%} "
            f"{r['total_trades']:>8} "
            f"{r['profit_factor']:>8.2f}"
        )

    # ── 最佳策略详细报告 ──────────────────────────────────────────────────────
    best = valid[0]
    click.echo("\n" + "=" * 80)
    click.echo(f"[BEST] 最佳策略: {best['strategy']}")
    click.echo("=" * 80)
    click.echo(f"  总收益率:   {best['total_return']:.2%}")
    click.echo(f"  年化收益:   {best['annual_return']:.2%}")
    click.echo(f"  最大回撤:   {best['max_drawdown']:.2%}")
    click.echo(f"  夏普比率:   {best['sharpe']:.2f}")
    click.echo(f"  索提诺:     {best['sortino']:.2f}")
    click.echo(f"  卡玛比率:   {best['calmar']:.2f}")
    click.echo(f"  胜率:       {best['win_rate']:.1%}")
    click.echo(f"  交易次数:   {best['total_trades']}")
    click.echo(f"  盈亏比:     {best['profit_factor']:.2f}")
    click.echo(f"  年化波动:   {best['volatility']:.4f}")

    # ── 综合评分 ──────────────────────────────────────────────────────────────
    click.echo("\n" + "=" * 80)
    click.echo("[*] 综合评分排名 (Sharpe*0.4 + Ret/DD*0.3 + WinRate*0.3)")
    click.echo("=" * 80)

    scored: list[tuple[dict[str, Any], float]] = []
    for r in valid:
        ret_dd_ratio = r["annual_return"] / r["max_drawdown"] if r["max_drawdown"] > 1e-6 else 999.0
        score = r["sharpe"] * 0.4 + ret_dd_ratio * 0.3 + r["win_rate"] * 100 * 0.3
        scored.append((r, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    click.echo(
        f"{'排名':>4}  {'策略':<22} {'综合评分':>10} {'夏普':>8} {'收益/回撤':>10} {'胜率':>8}"
    )
    click.echo("-" * 70)
    for i, (r, score) in enumerate(scored, 1):
        ret_dd_ratio = r["annual_return"] / r["max_drawdown"] if r["max_drawdown"] > 1e-6 else 999.0
        medal = " *1*" if i == 1 else " *2*" if i == 2 else " *3*" if i == 3 else "    "
        click.echo(
            f"{medal}{i:>2}  {r['strategy']:<22} {score:>10.2f} "
            f"{r['sharpe']:>8.2f} {ret_dd_ratio:>10.2f} {r['win_rate']:>7.1%}"
        )

    # ── 最佳策略交易明细 ──────────────────────────────────────────────────────
    best_name = valid[0]["strategy"]
    if best_name in backtest_results:
        bt = backtest_results[best_name]
        bp = bt.performance
        bc = bt.config

        click.echo("\n" + "=" * 80)
        click.echo(f"[DETAIL] 最佳策略交易明细: {best_name}")
        click.echo("=" * 80)

        click.echo("=== 回测绩效概要 ===")
        click.echo(f"总收益率: {bp.get('total_return', 0):.2%}")
        click.echo(f"年化收益: {bp.get('annual_return', 0):.2%}")
        click.echo(f"最大回撤: {bp.get('max_drawdown', 0):.2%}")
        click.echo(f"夏普比率: {bp.get('sharpe', 0):.2f}")
        click.echo(f"胜率: {bp.get('win_rate', 0):.2%}")
        click.echo(f"交易次数: {bp.get('total_trades', 0)}")
        click.echo()
        click.echo("=== 配置参数 ===")
        click.echo(f"初始资金: {bc.get('cash', 0):.2f}")
        click.echo(f"佣金率: {bc.get('commission', 0):.4f}")
        click.echo(f"成交规则: {bc.get('execution', 'next_open')}")
        click.echo()

        if not bt.trades.empty:
            click.echo("=== 最近交易记录 ===")
            recent_trades = bt.trades.tail(10)
            for _, trade in recent_trades.iterrows():
                direction = "买入" if trade["direction"] == "BUY" else "卖出"
                status = "拒绝" if trade["rejected"] else "成交"
                click.echo(
                    f"  [{trade['datetime']}] {direction} "
                    f"数量={trade['size']:.0f} 价格={trade['price']:.2f} "
                    f"盈亏={trade['pnl']:.2f} [{status}]"
                )
        else:
            click.echo("无交易记录")

    # ── 报告错误 ──────────────────────────────────────────────────────────────
    if errored:
        click.echo("\n[!] 以下策略运行失败:")
        for r in errored:
            click.echo(f"  {r['strategy']}: {r['error']}")

    return True


def _run_combo_screen(
    strategy_classes: dict[str, type],
    df: Any,
    cash: float,
    commission: float,
    combo_sizes: tuple[int, ...],
    combo_mode: str,
) -> None:
    """运行多因子组合回测并输出排名。"""
    from math import comb

    from ..backtest.combo import CombinationRunner

    classes_list = list(strategy_classes.values())
    if len(classes_list) < 2:
        click.echo("[!] 策略数量不足 2 个，跳过组合回测")
        return

    # 单个 Runner 跨 size 复用信号缓存，避免重复提取
    runner = CombinationRunner(
        strategy_classes=classes_list,
        df=df,
        cash=cash,
        commission=commission,
    )

    for size in combo_sizes:
        total = comb(len(classes_list), size)
        click.echo("\n" + "=" * 80)
        click.echo(f"[*] {size}因子组合回测 (共{total}组, 模式={combo_mode})")
        click.echo("=" * 80)

        results = runner.screen(combo_sizes=(size,), mode=combo_mode.upper())

        if not results:
            click.echo("  无有效交易组合（所有组合均为零交易）")
            continue

        click.echo(
            f"{'排名':>4}  {'因子组合':<50} {'总收益率':>10} {'年化收益':>10} "
            f"{'最大回撤':>10} {'夏普':>8} {'胜率':>8} {'交易':>6}"
        )
        click.echo("-" * 120)

        for i, r in enumerate(results[:20], 1):
            medal = " *1*" if i == 1 else " *2*" if i == 2 else " *3*" if i == 3 else "    "
            perf = r.result.performance
            click.echo(
                f"{medal}{i:>2}  {r.name:<50} "
                f"{perf.get('total_return', 0):>9.2%} "
                f"{perf.get('annual_return', 0):>9.2%} "
                f"{perf.get('max_drawdown', 0):>9.2%} "
                f"{perf.get('sharpe', 0):>8.2f} "
                f"{perf.get('win_rate', 0):>7.1%} "
                f"{perf.get('total_trades', 0):>6}"
            )

        if len(results) > 20:
            click.echo(f"  ... 共 {len(results)} 个有效组合，仅显示前 20")

        # 最佳组合详细报告
        best = results[0]
        bp = best.result.performance
        click.echo(f"\n[BEST {size}因子] {best.name}")
        click.echo(f"  总收益率: {bp.get('total_return', 0):.2%}")
        click.echo(f"  年化收益: {bp.get('annual_return', 0):.2%}")
        click.echo(f"  最大回撤: {bp.get('max_drawdown', 0):.2%}")
        click.echo(f"  夏普比率: {bp.get('sharpe', 0):.2f}")
        click.echo(f"  胜率:     {bp.get('win_rate', 0):.1%}")


def _show_best_chart(
    df: Any,
    result: Any,
    strategy_name: str,
    stock_label: str,
    stock_name: str,
    initial_cash: float,
) -> None:
    """展示最佳策略资金曲线与股价归一化对比图。"""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        click.echo("[!] 需要 matplotlib 才能展示图表: pip install matplotlib")
        return

    _setup_chinese_font()

    equity = result.equity_curve
    if equity.empty:
        click.echo("[!] 最佳策略无资金曲线数据，跳过绘图")
        return

    fig, ax1 = plt.subplots(figsize=(14, 7))

    # 归一化股价（以第一天收盘价为基准）
    close_prices = df["close"].values
    norm_price = close_prices / close_prices[0]
    dates = df["datetime"] if "datetime" in df.columns else df.index
    ax1.plot(dates, norm_price, color="steelblue", linewidth=1.2, label="股价 (归一化)")
    ax1.set_ylabel("股价归一化", color="steelblue", fontsize=11)
    ax1.tick_params(axis="y", labelcolor="steelblue")

    # 归一化资金曲线（以初始资金为基准）
    eq_dates = equity["datetime"]
    eq_values = equity["total"].values / initial_cash
    ax2 = ax1.twinx()
    ax2.plot(eq_dates, eq_values, color="crimson", linewidth=1.5, label=f"策略: {strategy_name}")
    ax2.set_ylabel("资金曲线 (归一化)", color="crimson", fontsize=11)
    ax2.tick_params(axis="y", labelcolor="crimson")

    # 标记买卖点
    trades = result.trades
    if not trades.empty:
        buy_trades = trades[trades["direction"] == "BUY"]
        sell_trades = trades[trades["direction"] == "SELL"]
        if not buy_trades.empty:
            ax2.scatter(
                buy_trades["datetime"].values,
                _map_trade_values(buy_trades, equity, initial_cash),
                marker="^",
                color="green",
                s=30,
                alpha=0.7,
                zorder=5,
                label="买入",
            )
        if not sell_trades.empty:
            ax2.scatter(
                sell_trades["datetime"].values,
                _map_trade_values(sell_trades, equity, initial_cash),
                marker="v",
                color="orange",
                s=30,
                alpha=0.7,
                zorder=5,
                label="卖出",
            )

    # 标题：股票代码 + 名称 + 策略绩效
    title = f"{stock_label}"
    if stock_name:
        title += f" {stock_name}"
    perf = result.performance
    ret_str = f"{perf.get('total_return', 0):.1%}"
    dd_str = f"{perf.get('max_drawdown', 0):.1%}"
    sharpe_str = f"{perf.get('sharpe', 0):.2f}"
    title += f"  |  最佳策略: {strategy_name}  |  收益 {ret_str}  回撤 {dd_str}  夏普 {sharpe_str}"

    ax1.set_title(title, fontsize=12, pad=15)
    ax1.set_xlabel("日期", fontsize=11)

    # 合并两个轴的图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)

    fig.autofmt_xdate()
    plt.tight_layout()
    click.echo("\n正在显示图表，关闭窗口后继续...")
    plt.show()


# ── 主命令 ──────────────────────────────────────────────────────────────────


@click.command("run-all")
@click.argument("market")
@click.argument("code")
@click.option("--count", default=2000, type=int, help="K线数量")
@click.option("--cash", default=1000000.0, type=float, help="初始资金")
@click.option("--commission", default=0.0003, type=float, help="佣金率")
@click.option("--adjust", default="QFQ", help="复权: NONE/QFQ/HFQ")
@click.option("--period", default="DAILY", help="K线周期")
@click.option(
    "--combo",
    "combo_sizes",
    multiple=True,
    type=int,
    help="多因子组合回测（可多次指定，如 --combo 2 --combo 3）",
)
@click.option(
    "--combo-mode",
    "combo_mode",
    default="MAJORITY",
    type=click.Choice(["AND", "OR", "MAJORITY"], case_sensitive=False),
    help="多因子信号合并模式（默认 MAJORITY）",
)
@click.option("--show", "show_chart", is_flag=True, help="显示最佳策略资金曲线 vs 股价对比图")
@click.option(
    "--strategies-dir",
    "strategies_dir",
    default="strategies",
    help="策略文件目录（默认 strategies/）",
)
def run_all(
    market: str,
    code: str,
    count: int,
    cash: float,
    commission: float,
    adjust: str,
    period: str,
    combo_sizes: tuple[int, ...],
    combo_mode: str,
    show_chart: bool,
    strategies_dir: str,
) -> None:
    """批量运行 strategies/ 目录下所有策略并比较结果。

    依次运行指定目录下所有策略文件，输出绩效排名和综合评分。

    示例：

      easy-tdx run-all SZ 300308 --count 2000 --cash 1000000 --adjust QFQ

      easy-tdx run-all SZ 300308 --combo 2 --combo-mode MAJORITY

      easy-tdx run-all SZ 300308 --show
    """
    from ..backtest.engine import BacktestEngine
    from ..cli.conn import get_mac_client
    from ..cli.parsers import parse_adjust, parse_market, parse_period

    # 1. 发现策略文件
    sdir = Path(strategies_dir)
    strategy_files = sorted(sdir.glob("*.py"))
    if not strategy_files:
        click.echo(f"未找到策略文件 ({strategies_dir}/*.py)", err=True)
        raise SystemExit(1)

    click.echo(f"发现 {len(strategy_files)} 个策略文件")
    click.echo(f"标的: {market} {code} | K线: {count} | 资金: {cash:,.0f} | 复权: {adjust}")
    click.echo("=" * 80)

    # 2. 获取数据（所有策略共享同一份数据）
    mkt = parse_market(market)
    click.echo("正在获取行情数据...")
    stock_name = ""
    with get_mac_client() as client:
        df = client.get_stock_kline(
            mkt,
            code,
            period=parse_period(period),
            start=0,
            count=count,
            adjust=parse_adjust(adjust),
        )
        # 获取股票名称（仅图表模式需要）
        if show_chart:
            try:
                quotes_df = client.get_stock_quotes([(mkt, code)])
                if not quotes_df.empty and "name" in quotes_df.columns:
                    stock_name = str(quotes_df.iloc[0]["name"])
            except Exception:
                pass
    click.echo(f"获取到 {len(df)} 条K线数据")
    click.echo("=" * 80)

    # 3. 逐个运行策略
    results: list[dict[str, Any]] = []
    backtest_results: dict[str, Any] = {}
    strategy_classes: dict[str, type] = {}

    for sf in strategy_files:
        strategy_name = sf.stem
        click.echo(f"\n>> 运行策略: {strategy_name} ...", nl=False)

        strategy_cls = _load_strategy_class(sf)
        if strategy_cls is None:
            click.echo(" [加载失败/无 Strategy 子类]")
            continue

        strategy_classes[strategy_name] = strategy_cls
        t0 = time.perf_counter()
        try:
            engine = BacktestEngine(
                strategy=strategy_cls,
                cash=cash,
                commission=commission,
            )
            result = engine.run(df)
            elapsed = time.perf_counter() - t0
            perf = result.performance
            click.echo(f" 完成 ({elapsed:.1f}s)")

            results.append(
                {
                    "strategy": strategy_name,
                    "total_return": perf.get("total_return", 0),
                    "annual_return": perf.get("annual_return", 0),
                    "max_drawdown": perf.get("max_drawdown", 0),
                    "sharpe": perf.get("sharpe", 0),
                    "sortino": perf.get("sortino", 0),
                    "calmar": perf.get("calmar", 0),
                    "win_rate": perf.get("win_rate", 0),
                    "total_trades": perf.get("total_trades", 0),
                    "profit_factor": perf.get("profit_factor", 0),
                    "volatility": perf.get("volatility", 0),
                }
            )
            backtest_results[strategy_name] = result
        except Exception as e:
            elapsed = time.perf_counter() - t0
            click.echo(f" 错误 ({elapsed:.1f}s): {e}")
            results.append({"strategy": strategy_name, "error": str(e)})

    # 4. 输出排名
    has_valid = _print_ranking(results, backtest_results)
    if not has_valid:
        raise SystemExit(1)

    # 5. 多因子组合回测
    if combo_sizes:
        _run_combo_screen(
            strategy_classes=strategy_classes,
            df=df,
            cash=cash,
            commission=commission,
            combo_sizes=combo_sizes,
            combo_mode=combo_mode,
        )

    # 6. 展示最佳策略曲线图
    if show_chart:
        valid = [r for r in results if "error" not in r]
        if valid:
            valid.sort(key=lambda x: x["total_return"], reverse=True)
            best_name = valid[0]["strategy"]
            if best_name in backtest_results:
                _show_best_chart(
                    df=df,
                    result=backtest_results[best_name],
                    strategy_name=best_name,
                    stock_label=f"{market}{code}",
                    stock_name=stock_name,
                    initial_cash=cash,
                )
