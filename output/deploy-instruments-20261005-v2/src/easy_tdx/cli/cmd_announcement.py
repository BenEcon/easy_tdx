"""公告检索命令（巨潮资讯网数据源，无需 TDX 服务器）。"""

from __future__ import annotations

import click


@click.command("announcement")
@click.argument("code")
@click.option("--count", default=30, type=int, help="每页数量")
@click.option("--page", default=1, type=int, help="页码（1 起始）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
@click.option(
    "--download",
    "download_n",
    type=int,
    default=0,
    help="下载最新 N 条公告的 PDF（0=不下载），需配合 --download-dir",
)
@click.option(
    "--download-dir",
    "download_dir",
    default=".",
    help="PDF 保存目录（默认当前目录，自动创建）",
)
def announcement(
    code: str,
    count: int,
    page: int,
    use_table: bool,
    output_fmt: str,
    download_n: int,
    download_dir: str,
) -> None:
    """检索公司公告（巨潮资讯网，独立数据源，无需连接 TDX）。

    \b
    示例：

      easy-tdx announcement 688017

      easy-tdx announcement 601088 --count 50 --page 2

      easy-tdx announcement 000001 --table

      # 下载最新 5 条公告的 PDF 到 ./pdfs 目录
      easy-tdx announcement 601088 --count 5 --download 5 --download-dir ./pdfs
    """
    from ..cninfo import CninfoClient, CninfoError
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt
    client = CninfoClient()
    try:
        df = client.get_announcements(code, count=count, page=page)
    except CninfoError as e:
        print_error(str(e))
        raise SystemExit(1) from e

    # 表格模式下不截断长文本列（url/title 经常超 30 字符，默认 output 会切到不可读）
    if fmt == "table":
        from .output import _render_table_full

        click.echo(_render_table_full(df))
    else:
        print_output(df, fmt)

    # PDF 下载
    if download_n > 0:
        if df.empty:
            print_error("无公告可下载")
            raise SystemExit(1)
        to_download = df.head(download_n)
        click.echo(f"开始下载 {len(to_download)} 条公告 PDF 到 {download_dir} ...", err=True)
        downloaded = 0
        skipped = 0
        # 复用 _query_announcements 已解析的 Announcement 对象需要重新查；
        # 这里直接从 DataFrame 行构造 Announcement 以避免二次网络请求。
        from ..cninfo.models import Announcement

        for _, row in to_download.iterrows():
            anno = Announcement(
                title=row["title"],
                type=row["type"],
                date=row["date"],
                url=row["url"],
                code=row["code"],
                org_id=row["org_id"],
                announcement_id=row["announcement_id"],
                announcement_time=row["announcement_time"],
                pdf_url=row["pdf_url"],
            )
            try:
                path = client.download_pdf(anno, dest_dir=download_dir)
                click.echo(f"  ✓ {path}", err=True)
                downloaded += 1
            except CninfoError as e:
                click.echo(f"  ✗ 跳过（{row['title'][:30]}）: {e}", err=True)
                skipped += 1
        click.echo(f"完成：{downloaded} 个下载，{skipped} 个跳过", err=True)
