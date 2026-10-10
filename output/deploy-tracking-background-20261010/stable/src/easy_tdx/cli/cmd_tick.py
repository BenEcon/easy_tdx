"""分时图命令。"""

from __future__ import annotations

import click


@click.command()
@click.argument("market")
@click.argument("code")
@click.option("--date", default=None, type=int, help="日期 YYYYMMDD（默认今天）")
@click.option("--days", default=1, type=int, help="天数（1或5）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def tick(
    market: str,
    code: str,
    date: int | None,
    days: int,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取分时图数据。

    示例：

      easy-tdx tick SZ 000001

      easy-tdx tick SH 600519 --days 5 --table

      easy-tdx tick SZ 000001 --date 20250115
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt
    mkt = parse_market(market)
    with get_mac_client() as client:
        if days > 1:
            df = client.get_tick_charts(mkt, code, date=date, days=days)
        else:
            df = client.get_tick_chart(mkt, code, date=date)
    print_output(df, fmt)
