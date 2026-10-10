"""easy-tdx serve — 启动 Web API 服务器。"""

from __future__ import annotations

import threading
import webbrowser

import click

from easy_tdx.cli.proxy import validated_forwarded_allow_ips


def _proxy_ips(ctx: click.Context, param: click.Parameter, value: str) -> str:
    try:
        return validated_forwarded_allow_ips(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc), ctx=ctx, param=param) from exc


@click.command("serve")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=8000, type=int, help="监听端口")
@click.option("--tdx-host", default=None, help="TDX 服务器地址（默认自动选择最优）")
@click.option("--tdx-port", default=None, type=int, help="TDX 服务器端口")
@click.option("--reload", is_flag=True, help="开发模式（自动重载）")
@click.option("--proxy-headers/--no-proxy-headers", default=True, help="仅信任指定代理的转发头")
@click.option(
    "--forwarded-allow-ips",
    default="127.0.0.1,::1",
    envvar="FORWARDED_ALLOW_IPS",
    callback=_proxy_ips,
    help="可信代理 IP/CIDR，逗号分隔；默认仅回环，禁止 *；可用 FORWARDED_ALLOW_IPS 设置",
)
@click.option(
    "--enable-ex/--disable-ex",
    default=None,
    help="启用扩展市场（港股/期货/外盘；默认读取 EASY_TDX_ENABLE_EX）",
)
@click.option(
    "--open-browser/--no-open-browser",
    default=True,
    help="启动后自动打开浏览器（默认开启，PyInstaller 打包后老人双击即用）",
)
def serve(
    host: str,
    port: int,
    tdx_host: str | None,
    tdx_port: int | None,
    reload: bool,
    proxy_headers: bool,
    forwarded_allow_ips: str,
    enable_ex: bool | None,
    open_browser: bool,
) -> None:
    """启动 Web API 服务器（需要安装 easy-tdx[web]）。"""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "错误：缺少 web 依赖。请运行: pip install easy-tdx[web]",
            err=True,
        )
        raise SystemExit(1) from None

    # 启动后延迟打开浏览器：uvicorn 需要约 1-2 秒绑定端口，过早打开会
    # 命中 connection refused。用后台 Timer 而非阻塞主线程。
    if open_browser and not reload:
        # 0.0.0.0 / 127.0.0.1 在浏览器里用 localhost 打开（更友好）。
        display_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
        url = f"http://{display_host}:{port}"
        # 1.5 秒通常足够本地端口就绪；uvicorn 启动慢的机器可适当延长。
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    if reload:
        uvicorn.run(
            "easy_tdx.web:app_factory",
            host=host,
            port=port,
            reload=True,
            factory=True,
            proxy_headers=proxy_headers and bool(forwarded_allow_ips),
            forwarded_allow_ips=forwarded_allow_ips,
            ws="websockets",
            ws_max_size=4096,
            ws_max_queue=8,
            ws_per_message_deflate=False,
        )
    else:
        from easy_tdx.web import create_app

        app = create_app(host=tdx_host, port=tdx_port, enable_ex=enable_ex)
        uvicorn.run(
            app,
            host=host,
            port=port,
            proxy_headers=proxy_headers and bool(forwarded_allow_ips),
            forwarded_allow_ips=forwarded_allow_ips,
            ws="websockets",
            ws_max_size=4096,
            ws_max_queue=8,
            ws_per_message_deflate=False,
        )
