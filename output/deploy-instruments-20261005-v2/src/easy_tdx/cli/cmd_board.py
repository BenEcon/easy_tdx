"""板块命令：board-list, board-members, belong-board。"""

from __future__ import annotations

import click

_SORT_CHOICES = [
    "CHANGE_PCT",
    "SPEED",
    "CHANGE_3D",
    "CHANGE_5D",
    "CHANGE_10D",
    "CHANGE_20D",
    "CHANGE_60D",
    "YTD",
]


@click.command("board-list")
@click.option("--type", "board_type", default="ALL", help="板块类型: ALL/HY/GN/FG/DQ/OTHER")
@click.option("--count", default=10000, type=int, help="请求数量")
@click.option(
    "--sort",
    "sort_column",
    default="CHANGE_PCT",
    type=click.Choice(_SORT_CHOICES),
    help=(
        "排序键，sort_value 列即该指标值；要取涨速传 SPEED"
        "（CHANGE_PCT 时该列恒 0，涨跌幅=price/pre_close-1）"
    ),
)
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def board_list(
    board_type: str,
    count: int,
    sort_column: str,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取板块列表。

    示例：

      easy-tdx board-list --table

      easy-tdx board-list --type GN --count 200

      easy-tdx board-list --type HY

      easy-tdx board-list --sort SPEED --table  # 按涨速排序，sort_value 即涨速%
    """
    from easy_tdx.mac.enums import BoardSortColumn

    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_board_type

    fmt = "table" if use_table else output_fmt
    bt = parse_board_type(board_type)
    sc = BoardSortColumn[sort_column]
    with get_mac_client() as client:
        df = client.get_board_list(board_type=bt, count=count, sort_column=sc)
    print_output(df, fmt)


@click.command("board-members")
@click.argument("board_symbol")
@click.option("--count", default=100000, type=int, help="请求数量")
@click.option(
    "--sort", "sort_field", default="CHANGE_PCT", help="排序字段: CHANGE_PCT/CODE/PRICE/VOLUME"
)
@click.option("--order", "sort_order", default="DESC", help="排序方向: DESC/ASC")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def board_members(
    board_symbol: str,
    count: int,
    sort_field: str,
    sort_order: str,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取板块成分股报价。

    BOARD_SYMBOL: 板块代码（如 881001）

    示例：

      easy-tdx board-members 881001 --table

      easy-tdx board-members 881001 --sort VOLUME --count 20
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_sort_order, parse_sort_type

    fmt = "table" if use_table else output_fmt
    st = parse_sort_type(sort_field)
    so = parse_sort_order(sort_order)
    with get_mac_client() as client:
        df = client.get_board_members(
            board_symbol,
            count=count,
            sort_type=st,
            sort_order=so,
        )
    print_output(df, fmt)


@click.command("belong-board")
@click.argument("market")
@click.argument("code")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def belong_board(market: str, code: str, use_table: bool, output_fmt: str) -> None:
    """获取个股所属板块列表。

    示例：

      easy-tdx belong-board SZ 000001

      easy-tdx belong-board SH 600519 --table
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt
    mkt = parse_market(market)
    with get_mac_client() as client:
        df = client.get_belong_board(mkt, code)
    print_output(df, fmt)


@click.command("board-summary")
@click.argument("board_symbol")
@click.option(
    "--sort", "sort_field", default="CHANGE_PCT", help="排序字段: CHANGE_PCT/CODE/PRICE/VOLUME"
)
@click.option("--order", "sort_order", default="DESC", help="排序方向: DESC/ASC")
@click.option("--members", "show_members", is_flag=True, help="输出成分股明细而非汇总")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def board_summary(
    board_symbol: str,
    sort_field: str,
    sort_order: str,
    show_members: bool,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取板块汇总（成交额、主力净流入、涨跌家数）。

    BOARD_SYMBOL: 板块代码（如 881001）

    示例：

      easy-tdx board-summary 881001 --table

      easy-tdx board-summary 881001 --members --table

      easy-tdx board-summary 881001 --sort VOLUME --order ASC
    """
    import pandas as pd

    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_sort_order, parse_sort_type

    fmt = "table" if use_table else output_fmt
    st = parse_sort_type(sort_field)
    so = parse_sort_order(sort_order)
    with get_mac_client() as client:
        result = client.get_board_summary(board_symbol, sort_type=st, sort_order=so)

    if show_members:
        members_df: pd.DataFrame = result["members"]
        print_output(members_df, fmt)
    else:
        summary = {k: v for k, v in result.items() if k != "members"}
        df = pd.DataFrame([summary])
        print_output(df, fmt)


@click.command("board-ranking")
@click.option("--type", "board_type", default="HY", help="板块类型: HY/GN")
@click.option("--top", "top_n", default=10, type=int, help="排行数量（默认 10）")
@click.option(
    "--sort-by",
    default="change_pct",
    help="排序字段: change_pct/amount/main_net_amount/vol",
)
@click.option("--asc", is_flag=True, help="升序（默认降序）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def board_ranking(
    board_type: str,
    top_n: int,
    sort_by: str,
    asc: bool,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取板块涨跌幅排行榜（行业/概念排行）。

    示例：

      easy-tdx board-ranking --table

      easy-tdx board-ranking --type GN --top 20 --table

      easy-tdx board-ranking --type HY --sort-by amount --asc
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_board_type

    fmt = "table" if use_table else output_fmt
    bt = parse_board_type(board_type)
    with get_mac_client() as client:
        df = client.get_board_ranking(board_type=bt, top_n=top_n, sort_by=sort_by, ascending=asc)
    print_output(df, fmt)


@click.command("board-change-ranking")
@click.option("--type", "board_type", default="HY", help="板块类型: HY/GN/FG/DQ/ALL")
@click.option("--date", "target_date", default=None, type=int, help="截止日期 YYYYMMDD (默认最新)")
@click.option("--days", default=20, type=int, help="回溯交易日数 (默认 20)")
@click.option("--top", "top_n", default=None, type=int, help="排行数量 (默认全部)")
@click.option("--asc", is_flag=True, help="升序 (默认降序)")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def board_change_ranking(
    board_type: str,
    target_date: int | None,
    days: int,
    top_n: int,
    asc: bool,
    use_table: bool,
    output_fmt: str,
) -> None:
    """获取板块 N 日涨跌幅排行榜。

    示例：

      easy-tdx board-change-ranking --table

      easy-tdx board-change-ranking --type GN --days 10 --top 15 --table

      easy-tdx board-change-ranking --type HY --date 20250530 --days 20 --table
    """
    from .conn import get_mac_client
    from .output import print_output
    from .parsers import parse_board_type

    fmt = "table" if use_table else output_fmt
    bt = parse_board_type(board_type)
    with get_mac_client() as client:
        df = client.get_board_change_ranking(
            board_type=bt,
            target_date=target_date,
            days=days,
            top_n=top_n,
            ascending=asc,
        )
    print_output(df, fmt)
