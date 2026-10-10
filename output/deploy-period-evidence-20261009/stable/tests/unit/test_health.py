"""服务器健康分（health score）引擎单元测试。

覆盖：
    - record_failure 乘性衰减 + 连续失败触发冷却
    - record_success 加性恢复 + 重置计数与冷却
    - is_in_cooldown / get_score 读取语义
    - rank_by_health：冷却剔除 + 有效延迟（latency/score）排序
    - 全健康时 rank_by_health 近似恒等映射（向后兼容保证）
"""

from __future__ import annotations

import time

import pytest

from easy_tdx._health import (
    _COOLDOWN_FAIL_THRESHOLD,
    _FAILURE_DECAY,
    _SUCCESS_RECOVER,
    get_score,
    is_in_cooldown,
    rank_by_health,
    record_failure,
    record_success,
    reset_health,
)


@pytest.fixture(autouse=True)
def _isolate_health():
    """每个测试前后清空健康记录，避免跨测试污染。"""
    reset_health()
    yield
    reset_health()


# --------------------------------------------------------------------------- #
# record_failure / record_success
# --------------------------------------------------------------------------- #


class TestRecordFailure:
    def test_single_failure_decays_score(self) -> None:
        s = record_failure("h1")
        assert s == pytest.approx(_FAILURE_DECAY)
        assert get_score("h1") == pytest.approx(_FAILURE_DECAY)

    def test_repeated_failure_decays_multiplicatively(self) -> None:
        record_failure("h1")
        record_failure("h1")
        s = record_failure("h1")
        assert s == pytest.approx(_FAILURE_DECAY**3)

    def test_consecutive_failures_below_threshold_no_cooldown(self) -> None:
        for _ in range(_COOLDOWN_FAIL_THRESHOLD - 1):
            record_failure("h1")
        assert not is_in_cooldown("h1")

    def test_consecutive_failures_at_threshold_enters_cooldown(self) -> None:
        for _ in range(_COOLDOWN_FAIL_THRESHOLD):
            record_failure("h1")
        assert is_in_cooldown("h1")

    def test_score_never_drops_below_floor(self) -> None:
        for _ in range(100):
            record_failure("h1")
        assert get_score("h1") > 0


class TestRecordSuccess:
    def test_success_recovers_score_additively(self) -> None:
        record_failure("h1")  # score = 0.5
        record_success("h1")
        assert get_score("h1") == pytest.approx(_FAILURE_DECAY + _SUCCESS_RECOVER)

    def test_success_caps_at_one(self) -> None:
        record_success("h1")
        record_success("h1")
        assert get_score("h1") == pytest.approx(1.0)

    def test_success_resets_consecutive_failures_and_cooldown(self) -> None:
        for _ in range(_COOLDOWN_FAIL_THRESHOLD):
            record_failure("h1")
        assert is_in_cooldown("h1")
        record_success("h1")
        assert not is_in_cooldown("h1")
        # 再次失败一次不应立即进冷却（计数已重置）
        record_failure("h1")
        assert not is_in_cooldown("h1")


# --------------------------------------------------------------------------- #
# is_in_cooldown
# --------------------------------------------------------------------------- #


class TestIsInCooldown:
    def test_unknown_host_not_in_cooldown(self) -> None:
        assert not is_in_cooldown("never-seen")

    def test_cooldown_expires(self) -> None:
        # 手动模拟过期：记录到阈值进入冷却后，快进时间戳
        for _ in range(_COOLDOWN_FAIL_THRESHOLD):
            record_failure("h1")
        assert is_in_cooldown("h1")
        # 直接篡改内部状态模拟冷却过期（避免真睡 120s）
        from easy_tdx._health import _BOOK

        with _BOOK.lock:
            _BOOK.hosts["h1"].cooldown_until = time.monotonic() - 1.0
        assert not is_in_cooldown("h1")


# --------------------------------------------------------------------------- #
# rank_by_health
# --------------------------------------------------------------------------- #


class TestRankByHealth:
    def test_identity_when_all_healthy(self) -> None:
        """全健康时输出排序与输入一致（向后兼容关键保证）。"""
        ranked = [("a", 0.01), ("b", 0.05), ("c", 0.10)]
        assert rank_by_health(ranked) == ranked

    def test_filters_out_cooldown_hosts(self) -> None:
        for _ in range(_COOLDOWN_FAIL_THRESHOLD):
            record_failure("bad")
        ranked = [("bad", 0.01), ("good", 0.02)]
        result = rank_by_health(ranked)
        assert "bad" not in [h for h, _ in result]
        assert result == [("good", 0.02)]

    def test_low_score_host_pushed_back(self) -> None:
        # b 延迟最低但 score 被打到很低，使其有效延迟（latency/score）反超 a。
        # 2 次失败 → b score = 0.25；有效延迟 = 0.03/0.25 = 0.12。
        # a 全健康，有效延迟 = 0.05/1.0 = 0.05 < 0.12 → a 应排前。
        for _ in range(2):
            record_failure("b")  # 不进冷却（阈值 3），但 score 衰减到 0.25
        ranked = [("b", 0.03), ("a", 0.05)]
        result = rank_by_health(ranked)
        assert result[0][0] == "a"

    def test_empty_input(self) -> None:
        assert rank_by_health([]) == []

    def test_preserves_latency_order_among_equal_scores(self) -> None:
        ranked = [("a", 0.01), ("b", 0.02), ("c", 0.03)]
        assert rank_by_health(ranked) == ranked
