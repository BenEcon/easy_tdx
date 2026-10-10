"""Standalone research worker service, independent of the HTTP process."""

from __future__ import annotations

import math
import signal
import sqlite3
from pathlib import Path
from threading import Event
from types import FrameType

import click


@click.command("research-worker")
@click.option(
    "--database",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="已有任务数据库，必须位于当前 EASY_TDX_CONFIG_DIR 账户目录内",
)
@click.option(
    "--poll-interval",
    default=0.2,
    type=click.FloatRange(min=0.01, max=5),
    help="队列与停止请求检查间隔（秒）",
)
@click.option(
    "--wall-seconds",
    default=600.0,
    type=click.FloatRange(min=0.01),
    help="从启动到监督器观察退出的时限（秒）",
)
@click.option(
    "--cpu-seconds",
    default=600,
    type=click.IntRange(min=1),
    help="每个计算进程的 CPU 时间上限（秒）",
)
@click.option(
    "--address-space-mib",
    default=None,
    type=click.IntRange(min=1),
    help="进程虚拟地址空间上限；Linux 默认 2048 MiB，macOS 默认不设此项",
)
@click.option(
    "--stop-grace",
    default=0.5,
    type=click.FloatRange(min=0.01, max=10),
    help="协作停止后到 terminate/kill 的等待间隔（秒）",
)
def research_worker(
    database: Path,
    poll_interval: float,
    wall_seconds: float,
    cpu_seconds: int,
    address_space_mib: int | None,
    stop_grace: float,
) -> None:
    """运行独立任务监督服务；不启动 HTTP，不主动获取行情。

    当前需明确指定已存在的任务库，普通 serve 尚未切换到此执行器。
    账户和任务数据库必须属于同一配置目录；不自动回收无法证明已死亡的旧执行。
    """
    if not math.isfinite(poll_interval):
        raise click.BadParameter("轮询间隔必须有限", param_hint="--poll-interval")
    from easy_tdx.web.account_store import _config_dir
    from easy_tdx.web.task_store import TaskStore
    from easy_tdx.web.task_supervisor import TaskSupervisor, WorkerLimits

    root = _config_dir().resolve()
    if database.resolve().parent != root or not (root / "accounts.db").is_file():
        raise click.ClickException(
            "任务库必须与已初始化的 accounts.db 位于当前配置目录，拒绝错配账户"
        )
    try:
        options = WorkerLimits(
            wall_seconds=wall_seconds,
            cpu_seconds=cpu_seconds,
            stop_grace_seconds=stop_grace,
            address_space_bytes=address_space_mib * 1024**2
            if address_space_mib is not None
            else WorkerLimits().address_space_bytes,
        )
        supervisor = TaskSupervisor(TaskStore(database), limits=options)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc)) from exc
    stop = Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    click.echo("独立研究任务服务已启动；关闭服务会在确认子进程退出后保留未完成输入。")
    if options.address_space_bytes is None:
        click.echo("提示：本平台未配置虚拟地址空间限制；这不代表已具备生产内存硬隔离。", err=True)
    try:
        while not stop.is_set():
            supervisor.step()
            stop.wait(poll_interval)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        try:
            supervisor.close()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
