"""连接重连与心跳策略的共享定义。

将原本在 ``client.py`` 与 ``mac/client.py`` 各自定义的 ``_RETRY_DELAYS``
提取到此统一来源，并供扩展行情 client（``ex/*``）复用，消除"6 处副本里
两套不一致韧性策略"的问题（审计报告 #2）。

复审（L1）补充：4 个 async client（A股 / MAC / 扩展行情 / 扩展 MAC）的
``_start_heartbeat`` / ``_stop_heartbeat`` / ``_heartbeat_loop`` 三件套此前
逐字节重复（仅心跳命令和 logger 名不同）。这里抽出
``AsyncHeartbeatMixin`` 收敛这些副本——子类只需实现 ``_heartbeat_cmd()``
返回一个 awaitable 即可，未来改心跳策略只需改一处。

跨主机故障转移（failover）：8 个 client 的 ``_execute`` 在同主机重试耗尽
（``_RETRY_DELAYS`` 走完仍 ``TdxConnectionError``）后，调用本模块的
``select_best_host_sync`` / ``select_best_host_async`` 重新测速、切到延迟
最低的**另一台**服务器再试一轮。这样服务器连不上时无需用户手动 ``ping``，
Python API / CLI / Web API 三入口自动生效（三者最终都汇聚到 ``_execute``）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from ._health import rank_by_health, record_failure, record_success
from .exceptions import TdxConnectionError, TdxDecodeError

# 连接断开时的指数退避序列（秒）。每次重连失败后按此序列 sleep 再重试，
# 共 4 次尝试（0.1 + 0.5 + 1.0 + 2.0 = 3.6s 总退避时间）。
# A 股 / MAC / 扩展行情 / 扩展 MAC 共 8 个 client 统一使用此序列。
_RETRY_DELAYS: tuple[float, ...] = (0.1, 0.5, 1.0, 2.0)

# 心跳失败时收窄的可重试异常（审计 #6）：仅连接/解析类异常视为"本次失败、
# 等下次重试"，不吞掉代码 bug 等非预期异常。子类无需重复声明此元组。
# exceptions 模块为纯定义、零导入，顶部导入无循环依赖风险。
_HEARTBEAT_RETRYABLE: tuple[type[BaseException], ...] = (
    OSError,
    TdxConnectionError,
    TdxDecodeError,
)

# --------------------------------------------------------------------------- #
# 跨主机故障转移（failover）共享实现
# --------------------------------------------------------------------------- #
#
# 设计要点：
# 1. 纯函数，不依赖任何 client 状态——8 个 client 各自传入自己的
#    (候选主机列表, 测速函数, 持久化函数, 端口)。便于单测、避免循环依赖。
# 2. 只返回与 current_host *不同* 的最优主机；若所有候选都不可达或唯一可达
#    的就是 current_host，返回 None（调用方保持原 host 不变）。
# 3. 进程级节流：_FAILOVER_PING_THROTTLE_SEC 秒内不重复全量测速——一次失败
#    可能触发多个并发请求同时进入 failover，节流避免对几十台服务器发起
#    "惊群"式测速。节流窗口内直接返回 None（放弃本次跨主机切换，让外层
#    同主机重试兜底）。

# 同一进程内两次全量测速的最小间隔（秒）。
_FAILOVER_PING_THROTTLE_SEC: float = 30.0

# 上次全量测速完成的时间戳（monotonic）；初始 0 表示"从未测过"。
_last_failover_ts: float = 0.0


def _throttled() -> bool:
    """距上次全量测速是否仍在节流窗口内（True=应跳过本次测速）。"""
    global _last_failover_ts
    return (time.monotonic() - _last_failover_ts) < _FAILOVER_PING_THROTTLE_SEC


def _mark_failover_done() -> None:
    """记录"本次全量测速已完成"，开启新一轮节流窗口。"""
    global _last_failover_ts
    _last_failover_ts = time.monotonic()


# 测速函数的统一签名：(hosts, port, timeout) -> [(host, latency_seconds), ...]
PingFn = Callable[..., list[tuple[str, float]]]
# 持久化函数的统一签名：(host) -> None
SaveFn = Callable[[str], None]


def select_best_host_sync(
    hosts: list[str],
    ping_fn: PingFn,
    save_fn: SaveFn,
    port: int,
    ping_timeout: float,
    current_host: str,
) -> str | None:
    """重新测速并选出优于当前主机的最佳主机（同步）。

    Args:
        hosts: 候选主机列表（如 ``get_known_hosts()``）。
        ping_fn: 测速函数（``ping_all`` / ``ping_mac_all`` / ``ping_ex_all``），
            签名 ``(hosts, port, timeout) -> [(host, latency), ...]``，已按
            延迟升序返回，不可达主机不在结果中。
        save_fn: 持久化函数（``save_best_host`` / ``save_best_ex_host`` /
            ``save_best_mac_ex_host``），将选中的主机写回 config.json。
        port: 目标端口。
        ping_timeout: 单台测速超时（秒）。
        current_host: 当前正在使用（且已判定不可用）的主机，结果会跳过它。

    Returns:
        选中的新主机（已 ``save_fn`` 持久化）；若无更优选择或处于节流窗口
        内，返回 ``None``（调用方保持原 host）。
    """
    if _throttled():
        logging.getLogger(__name__).debug(
            "跨主机故障转移：处于 %ss 节流窗口内，跳过本次测速",
            _FAILOVER_PING_THROTTLE_SEC,
        )
        return None
    try:
        ranked = ping_fn(hosts, port, ping_timeout)
    finally:
        # 无论测速是否拿到结果，都视为"完成一次测速"，开启节流窗口，
        # 避免失败时被高频重试反复触发。
        _mark_failover_done()
    # 健康分重排：冷却中的剔除，剩余按 latency/score（有效延迟）排序。
    # 全健康时近似恒等映射，对既有 mock 测试零影响。
    ranked = rank_by_health(ranked)
    # 跳过当前（已判定不可用）主机，取延迟最低的另一台
    for host, _latency in ranked:
        if host != current_host:
            save_fn(host)
            logging.getLogger(__name__).info("跨主机故障转移：从 %s 切换到 %s", current_host, host)
            return host
    return None


async def select_best_host_async(
    hosts: list[str],
    ping_fn: PingFn,
    save_fn: SaveFn,
    port: int,
    ping_timeout: float,
    current_host: str,
) -> str | None:
    """重新测速并选出优于当前主机的最佳主机（异步）。

    与 :func:`select_best_host_sync` 语义一致；测速在线程池中执行
    （``ping_fn`` 是阻塞实现，用 ``asyncio.to_thread`` 避免阻塞事件循环），
    节流与持久化语义不变。
    """
    if _throttled():
        logging.getLogger(__name__).debug(
            "跨主机故障转移：处于 %ss 节流窗口内，跳过本次测速",
            _FAILOVER_PING_THROTTLE_SEC,
        )
        return None
    try:
        ranked = await asyncio.to_thread(ping_fn, hosts, port, ping_timeout)
    finally:
        _mark_failover_done()
    # 健康分重排（与 sync 版对称）：冷却剔除 + 有效延迟排序。
    ranked = rank_by_health(ranked)
    for host, _latency in ranked:
        if host != current_host:
            save_fn(host)
            logging.getLogger(__name__).info("跨主机故障转移：从 %s 切换到 %s", current_host, host)
            return host
    return None


# 空数据故障转移时最多尝试多少台候选主机（按延迟升序）。统计指数等数据
# 并非所有服务器都提供，延迟最低的不一定返回数据，故需轮询前几台。
_WORKING_HOST_MAX_ATTEMPTS = 5

# 验证函数签名：(host) -> True 表示该主机可用（如返回非空数据）。
TryFn = Callable[[str], bool]
AsyncTryFn = Callable[[str], Awaitable[bool]]


def find_working_host_sync(
    ranked_hosts: list[tuple[str, float]],
    try_fn: TryFn,
    save_fn: SaveFn,
    current_host: str,
    max_attempts: int = _WORKING_HOST_MAX_ATTEMPTS,
) -> str | None:
    """按延迟顺序逐台测试候选主机，返回第一台"可用"的（同步）。

    与 :func:`select_best_host_sync` 的区别：后者只按延迟选一台（用于连接
    失败的故障转移）；本函数用于"连接成功但数据空"的场景（如 ``get_market_stat``
    的统计指数 880005/880001/880006 并非所有服务器都提供），需逐台实际查询
    才能确定哪台返回有效数据。

    Args:
        ranked_hosts: 已按延迟升序排序的 ``[(host, latency), ...]``（来自
            ``ping_fn`` 的返回值）。
        try_fn: 对单台主机的验证函数，返回 ``True`` 表示该主机可用（如返回
            非空数据）。调用方在其中负责连接、查询、清理。
        save_fn: 持久化函数，选中可用主机后调用。
        current_host: 当前主机（跳过，它已被判定不可用）。
        max_attempts: 最多尝试多少台候选（默认 5），避免极端情况下逐台试探
            全部候选拖垮响应。

    Returns:
        第一台可用的主机（已 ``save_fn`` 持久化）；全部不可用则返回 ``None``。
    """
    log = logging.getLogger(__name__)
    tried = 0
    # 健康分预过滤：剔除冷却中的主机，避免对"持续不可用"的服务器反复实测。
    ranked_hosts = rank_by_health(ranked_hosts)
    for host, _latency in ranked_hosts:
        if host == current_host:
            continue
        if tried >= max_attempts:
            break
        tried += 1
        try:
            if try_fn(host):
                save_fn(host)
                record_success(host)
                log.info(
                    "空数据故障转移：从 %s 切换到 %s（第 %d 台候选可用）",
                    current_host,
                    host,
                    tried,
                )
                return host
            # 连通但返回空数据：记一次失败降权，下次优先级下降
            record_failure(host)
        except Exception:
            # 验证单台主机时的任何异常（连接失败、解析错误等）都只跳过该台，
            # 继续尝试下一台，不让单台拖垮整个轮询。
            record_failure(host)
            log.debug("空数据故障转移：%s 验证失败，尝试下一台", host, exc_info=True)
    return None


async def find_working_host_async(
    ranked_hosts: list[tuple[str, float]],
    try_fn: AsyncTryFn,
    save_fn: SaveFn,
    current_host: str,
    max_attempts: int = _WORKING_HOST_MAX_ATTEMPTS,
) -> str | None:
    """按延迟顺序逐台测试候选主机，返回第一台"可用"的（异步）。

    与 :func:`find_working_host_sync` 语义一致；``try_fn`` 为 async 函数。
    """
    log = logging.getLogger(__name__)
    tried = 0
    # 健康分预过滤（与 sync 版对称）：剔除冷却中的主机。
    ranked_hosts = rank_by_health(ranked_hosts)
    for host, _latency in ranked_hosts:
        if host == current_host:
            continue
        if tried >= max_attempts:
            break
        tried += 1
        try:
            if await try_fn(host):
                save_fn(host)
                record_success(host)
                log.info(
                    "空数据故障转移：从 %s 切换到 %s（第 %d 台候选可用）",
                    current_host,
                    host,
                    tried,
                )
                return host
            # 连通但返回空数据：记一次失败降权
            record_failure(host)
        except Exception:
            record_failure(host)
            log.debug("空数据故障转移：%s 验证失败，尝试下一台", host, exc_info=True)
    return None


class AsyncHeartbeatMixin:
    """async client 心跳三件套的共享实现（审计复审 L1）。

    子类约定：
        - 在 ``__init__`` 中设置 ``self._heartbeat_interval: float`` 与
          ``self._heartbeat_task: asyncio.Task | None = None``；
        - 实现 ``_heartbeat_cmd()``，返回一个 awaitable（通常是一个轻量
          业务请求，用于保活并触发断线重连）。

    收敛后 ``_start_heartbeat`` / ``_stop_heartbeat`` / ``_heartbeat_loop``
    只此一份实现；心跳异常范围统一收窄为 (OSError, TdxConnectionError,
    TdxDecodeError)（审计 #6）。
    """

    # 类型提示（实际由子类 __init__ 赋值；此处仅服务于静态检查与文档）
    _heartbeat_interval: float
    _heartbeat_task: asyncio.Task[None] | None

    def _heartbeat_cmd(self) -> Awaitable[object]:
        """返回心跳使用的轻量请求 awaitable。子类必须覆写。"""
        raise NotImplementedError

    def _start_heartbeat(self) -> None:
        """启动后台心跳任务（若已在跑则先取消旧任务）。"""
        if self._heartbeat_interval <= 0:
            return
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _stop_heartbeat(self) -> None:
        """停止并清理心跳任务。"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """心跳循环：定期发送轻量级请求保活。

        失败语义：连接/解析类异常属于"本次失败、等下次重试"，下一次正常的
        业务请求或下一次心跳会通过 ``_execute`` 触发重连。非预期异常
        （代码 bug）不被吞掉，会冒泡打断心跳任务（审计 #6）。
        """
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                await self._heartbeat_cmd()
            except asyncio.CancelledError:
                break
            except _HEARTBEAT_RETRYABLE:
                logging.getLogger(__name__).debug(
                    "心跳失败，等待下次业务请求触发重连", exc_info=True
                )
