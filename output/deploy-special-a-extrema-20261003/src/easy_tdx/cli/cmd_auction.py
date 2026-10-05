"""集合竞价命令。"""

from __future__ import annotations

import click


@click.command()
@click.argument("market")
@click.argument("code")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def auction(market: str, code: str, use_table: bool, output_fmt: str) -> None:
    """获取集合竞价数据。

    示例：

      easy-tdx auction SZ 000001

      easy-tdx auction SH 600519 --table
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt
    mkt = parse_market(market)
    with get_mac_client() as client:
        df = client.get_auction(mkt, code)
    print_output(df, fmt)
