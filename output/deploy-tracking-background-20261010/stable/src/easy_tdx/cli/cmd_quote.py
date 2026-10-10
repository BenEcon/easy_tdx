"""报价命令：quote（单/批量）, quote-list（按分类排序）。"""

from __future__ import annotations

import click


@click.command()
@click.argument("stocks")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def quote(stocks: str, use_table: bool, output_fmt: str) -> None:
    """获取实时报价（支持多只）。

    STOCKS 格式: "SZ 000001,SH 600519"

    示例：

      easy-tdx quote "SZ 000001"

      easy-tdx quote "SZ 000001,SH 600519" --table
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_stocks

    fmt = "table" if use_table else output_fmt
    stock_list = parse_stocks(stocks)
    with get_mac_client() as client:
        df = client.get_stock_quotes(stock_list)
    print_output(df, fmt)


@click.command("quote-list")
@click.argument("category", default="A")
@click.option("--count", default=80, type=int, help="请求数量")
@click.option(
    "--sort",
    "sort_field",
    default="CHANGE_PCT",
    help="排序字段: CHANGE_PCT/CODE/PRICE/VOLUME/TOTAL_AMOUNT/TURNOVER_RATE",
)
@click.option("--order", "sort_order", default="DESC", help="排序方向: DESC/ASC")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def quote_list(
    category: str,
    count: int,
    sort_field: str,
    sort_order: str,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取市场分类报价列表（按涨幅等排序）。

    CATEGORY: SH/SZ/A/B/KCB/BJ/CYB/ETF/LOF/HGT/SGT 等

    示例：

      easy-tdx quote-list A --count 20 --table

      easy-tdx quote-list KCB --sort TOTAL_AMOUNT --order ASC

      easy-tdx quote-list CYB --count 50
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_category, parse_sort_order, parse_sort_type

    fmt = "table" if use_table else output_fmt
    cat = parse_category(category)
    st = parse_sort_type(sort_field)
    so = parse_sort_order(sort_order)
    with get_mac_client() as client:
        df = client.get_stock_quotes_list(
            category=cat,
            count=count,
            sort_type=st,
            sort_order=so,
        )
    print_output(df, fmt)
