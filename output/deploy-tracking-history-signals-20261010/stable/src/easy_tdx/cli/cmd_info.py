"""信息查询命令：server-info, symbol-info。"""

from __future__ import annotations

import click


@click.command("server-info")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def server_info(use_table: bool, output_fmt: str) -> None:
    """获取服务器交易时段信息。

    示例：

      easy-tdx server-info

      easy-tdx server-info --table
    """
    from .conn import get_mac_client
    from .output import print_output

    fmt = "table" if use_table else output_fmt
    with get_mac_client() as client:
        df = client.get_server_info()
    print_output(df, fmt)


@click.command("symbol-info")
@click.argument("market")
@click.argument("code")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def symbol_info(market: str, code: str, use_table: bool, output_fmt: str) -> None:
    """获取个股简要特征快照。

    示例：

      easy-tdx symbol-info SZ 000001

      easy-tdx symbol-info SH 600519 --table
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt
    mkt = parse_market(market)
    with get_mac_client() as client:
        df = client.get_symbol_info(mkt, code)
    print_output(df, fmt)
