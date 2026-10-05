"""市场监控命令：unusual, market-stat。"""

from __future__ import annotations

import click


@click.command()
@click.argument("market")
@click.option("--count", default=600, type=int, help="请求数量")
@click.option("--start", default=0, type=int, help="起始偏移")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def unusual(
    market: str,
    count: int,
    start: int,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取市场异动数据。

    示例：

      easy-tdx unusual SZ

      easy-tdx unusual SH --count 100 --table
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt
    mkt = parse_market(market)
    with get_mac_client() as client:
        df = client.get_unusual(mkt, start=start, count=count)
    print_output(df, fmt)


@click.command("market-stat")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def market_stat(use_table: bool, output_fmt: str) -> None:
    """获取 A 股全市场涨跌统计概况。

    示例：

      easy-tdx market-stat

      easy-tdx market-stat --table
    """
    from ..client import TdxClient
    from .output import print_output

    fmt = "table" if use_table else output_fmt
    with TdxClient.from_best_host() as client:
        df = client.get_market_stat()
    print_output(df, fmt)
