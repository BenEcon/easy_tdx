"""管理命令：ping, version。"""

from __future__ import annotations

import click


@click.command()
@click.option("--timeout", default=5.0, help="测速超时（秒）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def ping(timeout: float, use_table: bool, output_fmt: str) -> None:
    """测量通达信服务器延迟。

    示例：

      easy-tdx ping

      easy-tdx ping --timeout 3 --table
    """
    import pandas as pd

    from ..transport.sync import ping_all, ping_mac_all
    from .output import print_output

    fmt = "table" if use_table else output_fmt

    click.echo("正在测速标准服务器...", err=True)
    std_results = ping_all(timeout=timeout)
    click.echo("正在测速MAC服务器...", err=True)
    mac_results = ping_mac_all(timeout=timeout)

    rows: list[dict[str, str | float]] = []
    for host, latency in std_results:
        rows.append({"group": "standard", "host": host, "latency_ms": round(latency * 1000, 1)})
    for host, latency in mac_results:
        rows.append({"group": "mac", "host": host, "latency_ms": round(latency * 1000, 1)})

    df = pd.DataFrame(rows)
    print_output(df, fmt)


@click.command()
def version() -> None:
    """显示版本号。"""
    ver = __import__("importlib.metadata", fromlist=["version"]).version("easy-tdx")
    click.echo(f"easy-tdx {ver}")
