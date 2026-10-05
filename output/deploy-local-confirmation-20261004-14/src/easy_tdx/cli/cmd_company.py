"""通达信原生 F10 / 财务快照命令（TDX 协议，与 Web 层 ``/finance`` ``/company/*`` 同源）。

与 ``cmd_finance.py`` 的新浪三表（``f10``）区别：
  - ``f10``                走新浪 HTTP，输出多期结构化利润表/负债表/现金流
  - 本模块走通达信协议，输出最新一期财务快照 + F10 全文板块
"""

from __future__ import annotations

import click

from ..models.enums import Market
from .parsers import parse_market


@click.command("finance-info")
@click.argument("market")
@click.argument("code")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def finance_info(market: str, code: str, use_table: bool, output_fmt: str) -> None:
    """获取最新财务快照（通达信协议，30+ 项单期指标）。

    含股本结构、资产负债、利润、现金流、每股指标等最新一期数据。
    与 ``f10``（新浪多期三表）互补，本命令仅返回最新一期。

    \b
    示例：

      easy-tdx finance-info SH 600519 --table

      easy-tdx finance-info SZ 000001
    """
    from ..exceptions import TdxError
    from .conn import get_tdx_client
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt
    mkt = Market(parse_market(market))
    try:
        with get_tdx_client() as client:
            df = client.get_finance_info(mkt, code)
    except TdxError as e:
        print_error(str(e))
        raise SystemExit(1) from e
    print_output(df, fmt)


@click.command("company-info")
@click.argument("market")
@click.argument("code")
@click.argument("name_or_filename", required=False, default=None)
@click.option("--table", "use_table", is_flag=True, help="表格输出（仅列目录时生效）")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
@click.option(
    "--offset",
    default=0,
    type=int,
    help="仅传文件名时生效：文件绝对偏移（字节，默认 0）",
)
@click.option(
    "--length",
    default=1024,
    type=int,
    help="仅传文件名时生效：读取长度（字节，默认 1024）",
)
def company_info(
    market: str,
    code: str,
    name_or_filename: str | None,
    use_table: bool,
    output_fmt: str,
    offset: int,
    length: int,
) -> None:
    """获取 F10 公司信息：无板块名参数列目录，有板块名参数读正文。

    \b
    两种用法：

      # 1. 列出 F10 板块目录（最新提示/公司概况/财务分析/... 共 16 板块）
      easy-tdx company-info SH 600519 --table

      # 2. 读取指定板块的完整正文（板块名自动解析定位，自动读全，无需 offset/length）
      easy-tdx company-info SH 600519 "公司概况"
      easy-tdx company-info SH 600519 "公司大事"     # 大板块自动分块循环读全

    \b
    传板块名时自动读取该板块完整内容（按目录里的 length 分块循环，单次上限
    30720 字节），用户无需关心 offset/length。
    也可直接传文件名（如 ``601088.txt``），此时用 --offset（文件绝对偏移，默认 0）
    和 --length（读取字节数，默认 1024）控制读取范围。
    """
    mkt = Market(parse_market(market))
    if name_or_filename is None:
        _run_category(mkt, code, use_table, output_fmt)
    else:
        _run_content(mkt, code, name_or_filename, offset, length)


@click.command("company-info-content", hidden=True)
@click.argument("market")
@click.argument("code")
@click.argument("name_or_filename")
@click.option(
    "--offset",
    default=0,
    type=int,
    help="偏移（字节）：传板块名时为板块内相对偏移，传文件名时为文件绝对偏移，默认 0",
)
@click.option("--length", default=1024, type=int, help="读取长度（字节，默认 1024）")
def company_info_content(
    market: str, code: str, name_or_filename: str, offset: int, length: int
) -> None:
    """[已弃用，改用 company-info] 读取 F10 公司信息板块正文。

    此命令为向后兼容保留（隐藏，不出现在 --help）。新用法::

        easy-tdx company-info SH 600519 "公司概况"
    """
    mkt = Market(parse_market(market))
    _run_content(mkt, code, name_or_filename, offset, length)


# --------------------------------------------------------------------------- #
# 内部实现：列目录 / 读正文
# --------------------------------------------------------------------------- #


def _run_category(market: Market, code: str, use_table: bool, output_fmt: str) -> None:
    """列出 F10 板块目录并输出。"""
    from ..exceptions import TdxError
    from .conn import get_tdx_client
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt
    try:
        with get_tdx_client() as client:
            df = client.get_company_info_category(market, code)
    except TdxError as e:
        print_error(str(e))
        raise SystemExit(1) from e
    print_output(df, fmt)


def _run_content(
    market: Market, code: str, name_or_filename: str, offset: int, length: int
) -> None:
    """读取 F10 板块正文并输出。

    传板块名时自动读取该板块**完整内容**（按目录里的 length 分块循环，单次上限
    30720 字节）；--offset/--length 仅在传文件名时生效。

    通达信多服务器返回的 F10 目录版本可能不一致（有的含新板块名、有的含旧板块名），
    因此传板块名时若未命中会重试多个服务器（新建连接），直至命中或耗尽。
    """
    from ..exceptions import TdxError
    from .conn import get_tdx_client
    from .output import print_error

    # 形如 '601088.txt' 的文件名，直接读，无需查目录
    if "." in name_or_filename:
        try:
            with get_tdx_client() as client:
                content = client.get_company_info_content(
                    market, code, name_or_filename, offset, length
                )
        except TdxError as e:
            print_error(str(e))
            raise SystemExit(1) from e
        click.echo(content)
        return

    # 板块名：多服务器重试，直到命中
    max_attempts = 4
    last_available = ""
    for _ in range(max_attempts):
        try:
            with get_tdx_client() as client:
                filename, seg_start, seg_length, matched_board = _resolve_filename(
                    client, market, code, name_or_filename
                )
        except _ResolveError as e:
            last_available = str(e)
            continue
        except TdxError as e:
            last_available = str(e)
            continue

        try:
            content = _read_full_section(client, market, code, filename, seg_start, seg_length)
        except TdxError as e:
            print_error(str(e))
            raise SystemExit(1) from e
        click.echo(content)
        return

    # 全部重试未命中
    detail = f"\n{last_available}" if last_available else ""
    print_error(f"未找到板块名 '{name_or_filename}'（已尝试 {max_attempts} 个服务器）。{detail}")
    raise SystemExit(1)


def _read_full_section(
    client: object, market: Market, code: str, filename: str, start: int, length: int
) -> str:
    """分块循环读取板块完整内容（单次上限 30720 字节）。

    offset/length 均为服务器端字节偏移，按请求的 n 推进 pos
    （解码后字符串无法精确还原字节数，且有 GBK 无法解码的字节会产生 U+FFFD）。
    """
    chunk_size = 30720
    parts: list[str] = []
    pos = start
    end = start + length
    while pos < end:
        n = min(chunk_size, end - pos)
        chunk = client.get_company_info_content(market, code, filename, pos, n)  # type: ignore[attr-defined]
        if not chunk:
            break
        parts.append(chunk)
        pos += n  # 服务器按请求的字节数推进偏移
    return "".join(parts)


class _ResolveError(Exception):
    """板块名解析失败（内部信号异常，与 TdxError 分开捕获）。"""


def _resolve_filename(
    client: object, market: Market, code: str, name_or_filename: str
) -> tuple[str, int, int, bool]:
    """把板块名解析为 (filename, 板块起始 offset, 板块长度, True)。

    注意：通达信多服务器目录版本不一致，命中与否取决于连到哪台服务器，
    调用方应配合重试（见 _run_content）。未命中抛 _ResolveError（含可用板块名）。
    仅处理板块名；文件名解析在 _run_content 顶部完成。
    """
    df = client.get_company_info_category(market, code)  # type: ignore[attr-defined]
    if not df.empty:
        row = df.loc[df["name"] == name_or_filename]
        if not row.empty:
            return (
                str(row["filename"].iloc[0]),
                int(row["start"].iloc[0]),
                int(row["length"].iloc[0]),
                True,
            )

    available = "、".join(df["name"].tolist()) if not df.empty else ""
    raise _ResolveError(
        f"可用板块：{available}" if available else "请先运行 `easy-tdx company-info` 查看目录。"
    )
