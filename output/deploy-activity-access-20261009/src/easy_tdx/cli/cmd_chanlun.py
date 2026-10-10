"""缠论分析命令。"""

from __future__ import annotations

import json
from typing import Any

import click


@click.command()
@click.argument("market")
@click.argument("code")
@click.option(
    "--period", default="DAILY", help="K线周期: DAILY/5MIN/15MIN/30MIN/60MIN/1MIN/WEEKLY/MONTHLY"
)
@click.option("--count", default=800, type=int, help="K线数量")
@click.option("--adjust", default="NONE", help="复权: NONE/QFQ/HFQ")
@click.option(
    "--multi-level",
    "low_level_period",
    default=None,
    help="低级别周期（多级别联立），如 30MIN；分析高级别最后一笔在低级别中的走势",
)
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def chanlun(
    market: str,
    code: str,
    period: str,
    count: int,
    adjust: str,
    low_level_period: str | None,
    use_table: bool,
    output_fmt: str,
) -> None:
    """缠论分析：计算 K 线的笔、中枢等缠论指标。

    示例：

      easy-tdx chanlun SZ 000001

      easy-tdx chanlun SH 600519 --adjust QFQ --table

      easy-tdx chanlun SZ 000001 --period 30MIN

      easy-tdx chanlun SZ 000001 --multi-level 30MIN --table

      easy-tdx chanlun SZ 000001 --multi-level 5MIN
    """
    from ..chanlun.analyser import ChanlunAnalyser
    from .conn import get_mac_client
    from .parsers import parse_adjust, parse_market, parse_period

    mkt = parse_market(market)
    with get_mac_client() as client:
        df = client.get_stock_kline(
            mkt,
            code,
            period=parse_period(period),
            start=0,
            count=count,
            adjust=parse_adjust(adjust),
        )

        analyser = ChanlunAnalyser(code=code, frequency=period)
        result = analyser.process_klines(df)

        result_dict = result.to_dict()

        # 多级别联立分析（需要在 with 块内使用 client 获取低级别数据）
        multi_level_info: dict[str, Any] | None = None
        if low_level_period is not None:
            multi_level_info = _run_multi_level(
                client, mkt, code, period, low_level_period, count, adjust, analyser, result
            )
            if multi_level_info is not None:
                result_dict["multi_level"] = multi_level_info

    fmt = "table" if use_table else output_fmt
    if fmt == "json":
        click.echo(json.dumps(result_dict, ensure_ascii=False, indent=2))
    elif fmt == "table":
        _print_table(result_dict)
    else:
        click.echo(json.dumps(result_dict, ensure_ascii=False))


def _print_table(result: dict[str, Any]) -> None:
    """以表格形式输出缠论分析结果。"""
    click.echo(f"标的: {result['code']}  周期: {result['frequency']}")
    click.echo(f"原始K线: {result['kline_count']}  缠论K线: {result['ckline_count']}")
    click.echo(
        f"分型: {result['fractal_count']}  笔: {result['bi_count']}  "
        f"中枢: {result['zs_count']}  线段: {result.get('xd_count', 0)}"
    )
    mmd_count = result.get("mmd_count", 0)
    bc_count = result.get("bc_count", 0)
    if mmd_count or bc_count:
        click.echo(f"买卖点: {mmd_count}  背驰: {bc_count}")
    click.echo()

    if result["bis"]:
        click.echo("── 笔 ──")
        for bi in result["bis"]:
            direction = "↑" if bi["direction"] == "up" else "↓"
            done = "✓" if bi["done"] else "…"
            click.echo(
                f"  [{bi['index']}] {direction} "
                f"{bi['start_date']} → {bi['end_date']} "
                f"h={bi['high']} l={bi['low']} {done}"
            )
        click.echo()

    if result["zss"]:
        click.echo("── 中枢 ──")
        for zs in result["zss"]:
            done = "✓" if zs["done"] else "…"
            click.echo(
                f"  [{zs['index']}] "
                f"{zs['start_date'] or '—'} → {zs['end_date'] or '—'} "
                f"zg={zs['zg']} zd={zs['zd']} "
                f"gg={zs['gg']} dd={zs['dd']} "
                f"lines={zs['line_count']} {done}"
            )
        click.echo()

    if result.get("xds"):
        click.echo("── 线段 ──")
        for xd in result["xds"]:
            direction = "↑" if xd["direction"] == "up" else "↓"
            click.echo(
                f"  [{xd['index']}] {direction} "
                f"{xd['start_date']} → {xd['end_date']} "
                f"h={xd['high']} l={xd['low']}"
            )
        click.echo()

    if result.get("mmds"):
        click.echo("── 买卖点 ──")
        for mmd in result["mmds"]:
            click.echo(f"  {mmd['type']} ({mmd['date'] or '—'}): {mmd['msg']}")
        click.echo()

    if result.get("bcs"):
        click.echo("── 背驰 ──")
        for bc in result["bcs"]:
            status = "✓" if bc["bc"] else "✗"
            prev = bc["prev_date"] or "—"
            curr = bc["curr_date"] or "—"
            click.echo(f"  [{status}] {bc['type']} ({prev} → {curr}): {bc['msg']}")

    if result.get("multi_level"):
        ml = result["multi_level"]
        click.echo("── 多级别联立 ──")
        click.echo(f"  高级别: {ml.get('high_level', '?')}  低级别: {ml.get('low_level', '?')}")
        qs = ml.get("low_level_qs", {})
        if qs:
            direction = qs.get("trend_direction")
            dir_str = {"up": "↑ 上升", "down": "↓ 下降"}.get(str(direction), "— 盘整")
            click.echo(f"  低级别笔: {qs.get('bi_count', 0)}  中枢: {qs.get('zs_count', 0)}")
            click.echo(
                f"  趋势方向: {dir_str}  "
                f"趋势: {'是' if qs.get('has_trend') else '否'}  "
                f"盘整: {'是' if qs.get('has_consolidation') else '否'}"
            )
            click.echo(
                f"  笔重叠: {'是' if qs.get('bi_overlap') else '否'}  "
                f"背驰可能: {'是' if qs.get('divergence_possible') else '否'}"
            )
        click.echo()


def _run_multi_level(
    client: Any,
    mkt: Any,
    code: str,
    high_period: str,
    low_period: str,
    count: int,
    adjust: str,
    high_analyser: Any,
    high_result: Any,
) -> dict[str, Any] | None:
    """运行多级别联立分析。

    获取低级别数据，分析高级别最后一笔在低级别中的走势结构。

    Args:
        client: TdxClient 实例
        mkt: Market 枚举值
        code: 股票代码
        high_period: 高级别周期
        low_period: 低级别周期
        count: K线数量
        adjust: 复权方式
        high_analyser: 高级别分析器（已处理）
        high_result: 高级别分析结果

    Returns:
        多级别分析信息字典，或 None（数据不足时）
    """
    from ..chanlun.analyser import ChanlunAnalyser
    from ..chanlun.multi_level import MultiLevelAnalyser
    from .parsers import parse_adjust, parse_period

    # 高级别最后一笔
    if not high_result.bis:
        return None

    last_bi = high_result.bis[-1]

    # 获取低级别数据（需要更多 K 线来覆盖高级别笔的时间范围）
    df_low = client.get_stock_kline(
        mkt,
        code,
        period=parse_period(low_period),
        start=0,
        count=min(count * 8, 8000),  # 低级别需要更多数据
        adjust=parse_adjust(adjust),
    )

    low_analyser = ChanlunAnalyser(code=code, frequency=low_period)

    mla = MultiLevelAnalyser()
    mla.add_level("high", high_analyser)
    mla.add_level("low", low_analyser)
    # 高级别已经处理过，只需注册；低级别需要处理
    mla.process("low", df_low)

    qs = mla.query_low_level_qs("high", "low", last_bi)

    return {
        "high_level": high_period,
        "low_level": low_period,
        "last_bi_index": last_bi.index if hasattr(last_bi, "index") else None,
        "low_level_qs": qs,
    }
