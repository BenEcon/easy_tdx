"""逐笔成交命令。"""

from __future__ import annotations

import click


@click.command()
@click.argument("market")
@click.argument("code")
@click.option("--count", default=2000, type=int, help="请求数量")
@click.option("--start", default=0, type=int, help="起始偏移")
@click.option("--date", default=None, type=int, help="日期 YYYYMMDD（默认今天）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def transaction(
    market: str,
    code: str,
    count: int,
    start: int,
    date: int | None,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取逐笔成交数据。

    示例：

      easy-tdx transaction SZ 000001

      easy-tdx transaction SH 600519 --count 500 --table

      easy-tdx transaction SZ 000001 --date 20250115
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt
    mkt = parse_market(market)
    with get_mac_client() as client:
        df = client.get_transactions(mkt, code, count=count, start=start, date=date)
    print_output(df, fmt)
