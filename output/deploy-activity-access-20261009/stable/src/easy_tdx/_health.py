"""服务器健康分（health score）引擎。

为通达信候选主机维护一份**进程级**的健康记录：每次失败降权、连续失败
触发冷却、成功缓慢恢复。``select_best_host_*`` / ``find_working_host_*``
据此重排候选列表，让"延迟低但数据不全 / 频繁断连"的服务器自动靠后，
避免被低延迟反复选中又反复触发空数据故障转移（日志里"服务器跳来跳去"
的根因之一）。

设计要点：
    1. 模块级单例 + ``threading.Lock``。8 个 client（A股/MAC/EX/MAC-EX ×
       sync/async）共享同一份记录——一台服务器的好坏不分协议。
    2. score ∈ ``(0, 1.0]``，初始 1.0。``record_failure`` 乘性衰减（×0.5），
       连续失败 ≥ ``_COOLDOWN_FAIL_THRESHOLD`` 台进入 ``_COOLDOWN_SEC`` 秒
       冷却期；``record_success`` 加性恢复（+0.2，上限 1.0）并重置计数。
    3. ``rank_by_health`` 把 ping 结果按 ``latency / score`` 重排（score 越低
       惩罚越大），冷却中的主机直接剔除——既非永久黑名单（恢复后可回归），
       也非纯延迟（数据不全的低延迟服务器会被压下去）。
    4. 全健康时 ``rank_by_health`` 近似恒等映射，对既有 failover 单测零影响。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 可调常数
# ---------------------------------------------------------------------------

# 失败一次的乘性衰减因子。score *= _FAILURE_DECAY（0.5 → 失败 3 次后 score ≈ 0.125）。
_FAILURE_DECAY: float = 0.5

# 成功一次的加性恢复量。score += _SUCCESS_RECOVER（上限 1.0）。
_SUCCESS_RECOVER: float = 0.2

# 进入冷却所需的连续失败次数。达到即认为该主机"持续不可用"，冷却期内剔除。
_COOLDOWN_FAIL_THRESHOLD: int = 3

# 冷却时长（秒）。冷却期内 ``is_in_cooldown`` 返回 True，``rank_by_health`` 剔除该主机。
_COOLDOWN_SEC: float = 120.0

# score 下限：保留一个极小正值而非归零，确保恢复路径可达且不会除零。
_SCORE_FLOOR: float = 1e-3


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------


@dataclass
class _HostHealth:
    """单台主机的健康记录。"""

    score: float = 1.0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0  # monotonic 时间戳；0 表示未进入冷却


@dataclass
class _HealthBook:
    """所有主机的健康记录簿（模块单例）。"""

    hosts: dict[str, _HostHealth] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _get(self, host: str) -> _HostHealth:
        hh = self.hosts.get(host)
        if hh is None:
            hh = _HostHealth()
            self.hosts[host] = hh
        return hh


_BOOK = _HealthBook()


# ---------------------------------------------------------------------------
# 写入：失败 / 成功 / 重置
# ---------------------------------------------------------------------------


def record_failure(host: str) -> float:
    """记录一次失败：score 乘性衰减，连续失败达阈值则进入冷却。

    Returns:
        衰减后的 score（便于调用方记录日志）。
    """
    now = time.monotonic()
    with _BOOK.lock:
        hh = _BOOK._get(host)
        hh.score = max(_SCORE_FLOOR, hh.score * _FAILURE_DECAY)
        hh.consecutive_failures += 1
        if hh.consecutive_failures >= _COOLDOWN_FAIL_THRESHOLD:
            hh.cooldown_until = now + _COOLDOWN_SEC
        return hh.score


def record_success(host: str) -> None:
    """记录一次成功：score 加性恢复（上限 1.0），重置连续失败计数与冷却。"""
    with _BOOK.lock:
        hh = _BOOK._get(host)
        hh.score = min(1.0, hh.score + _SUCCESS_RECOVER)
        hh.consecutive_failures = 0
        hh.cooldown_until = 0.0


def reset_health() -> None:
    """清空全部健康记录。主要供测试隔离使用。"""
    with _BOOK.lock:
        _BOOK.hosts.clear()


# ---------------------------------------------------------------------------
# 读取：冷却判定 / 健康分 / 排序
# ---------------------------------------------------------------------------


def is_in_cooldown(host: str) -> bool:
    """该主机是否处于冷却期（True=应剔除，暂不选用）。"""
    now = time.monotonic()
    with _BOOK.lock:
        hh = _BOOK.hosts.get(host)
        if hh is None:
            return False
        return hh.cooldown_until > now


def get_score(host: str) -> float:
    """返回该主机当前 score（无记录则 1.0）。"""
    with _BOOK.lock:
        hh = _BOOK.hosts.get(host)
        return hh.score if hh is not None else 1.0


def rank_by_health(
    ranked_hosts: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    """按健康分重排 ping 结果。

    输入是 ``ping_all`` 返回的 ``[(host, latency), ...]``（已按延迟升序）。
    本函数：
        1. 剔除处于冷却期的主机；
        2. 对剩余主机按 ``latency / score``（有效延迟）升序排序——score 越低
           惩罚越大，但低延迟仍占优，两者平滑权衡。

    全健康时（所有 score=1.0、无冷却），输出与输入排序一致（恒等映射），
    故对既有 ``test_failover.py`` 的 mock 测试零影响。
    """
    now = time.monotonic()
    with _BOOK.lock:
        kept: list[tuple[str, float, float]] = []
        for host, latency in ranked_hosts:
            hh = _BOOK.hosts.get(host)
            if hh is not None and hh.cooldown_until > now:
                # 冷却中：剔除
                continue
            score = hh.score if hh is not None else 1.0
            kept.append((host, latency, score))
    # 有效延迟 = latency / score；score 越小有效延迟越大，越靠后
    kept.sort(key=lambda t: t[1] / t[2])
    return [(h, lat) for h, lat, _ in kept]
