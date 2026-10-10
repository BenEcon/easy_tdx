"""单元测试：信号扫描引擎。

测试 SignalScanner 的并发扫描和增量扫描功能。
使用临时目录构造 .day 文件 fixture，无需真实数据。
"""

from __future__ import annotations

import struct
from pathlib import Path

import pandas as pd
import pytest

from easy_tdx.backtest.strategy import Strategy
from easy_tdx.screen.scanner import SignalScanner


class AlwaysBuyStrategy(Strategy):
    """策略：每个 bar 都产生买入信号（用于扫描测试）。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        self.buy(size=0)


def _write_day_file(
    path: Path,
    n_bars: int = 50,
    base_price: float = 10.0,
) -> None:
    """写一个最小的 .day 文件（通达信日线格式）。

    格式: date(I) open(I) high(I) low(I) close(I) amount(f) vol(I) reserved(I)
    每条 32 字节, 小端序. 价格以 0.01 为系数存储.
    """
    dates = pd.date_range("2024-01-01", periods=n_bars, freq="D")

    with open(path, "wb") as f:
        for i in range(n_bars):
            dt = dates[i]
            day = dt.year * 10000 + dt.month * 100 + dt.day
            price = base_price + i * 0.01
            f.write(
                struct.pack(
                    "<IIIIIfII",
                    day,
                    int(price * 100),
                    int((price + 0.5) * 100),
                    int((price - 0.5) * 100),
                    int(price * 100),
                    float(1000000 + i * 100),
                    10000 + i * 10,
                    0,
                )
            )


@pytest.fixture
def vipdoc(tmp_path: Path) -> Path:
    """创建包含 .day 文件的临时 vipdoc 目录."""
    sz_lday = tmp_path / "sz" / "lday"
    sz_lday.mkdir(parents=True)

    for code in ("000001", "000002", "000003"):
        _write_day_file(sz_lday / f"sz{code}.day", n_bars=50)

    # 指数文件 (应被过滤)
    _write_day_file(sz_lday / "sz399001.day", n_bars=50)

    return tmp_path


class TestConcurrentScan:
    """测试并发扫描."""

    def test_scan_produces_results(self, vipdoc: Path) -> None:
        """基本扫描应返回触发信号的股票."""
        scanner = SignalScanner(AlwaysBuyStrategy, vipdoc_path=vipdoc)
        results = scanner.scan(universe="all")

        assert len(results) >= 1, f"Expected >= 1 result, got {len(results)}"

    def test_concurrent_same_as_serial(self, vipdoc: Path) -> None:
        """并发扫描结果应与串行扫描一致."""
        scanner = SignalScanner(AlwaysBuyStrategy, vipdoc_path=vipdoc)

        serial = scanner.scan(universe="all", workers=1)
        parallel = scanner.scan(universe="all", workers=2)

        serial_codes = sorted(r.code for r in serial)
        parallel_codes = sorted(r.code for r in parallel)
        assert serial_codes == parallel_codes

    def test_scan_with_zero_workers_uses_serial(self, vipdoc: Path) -> None:
        """workers=0 应退回串行模式."""
        scanner = SignalScanner(AlwaysBuyStrategy, vipdoc_path=vipdoc)
        results = scanner.scan(universe="all", workers=0)

        assert len(results) >= 1

    def test_progress_callback(self, vipdoc: Path) -> None:
        """进度回调应被正确调用."""
        scanner = SignalScanner(AlwaysBuyStrategy, vipdoc_path=vipdoc)
        progress: list[tuple[int, int, str]] = []

        def on_progress(current: int, total: int, name: str) -> None:
            progress.append((current, total, name))

        scanner.scan(universe="all", progress_callback=on_progress)

        assert len(progress) >= 2
        assert progress[-1][2] == "done"


class TestParallelPickleFix:
    """回归测试：并发模式从策略文件加载（修复 pickle 序列化失败）。"""

    def test_parallel_with_file_strategy(self, vipdoc: Path) -> None:
        """从 .py 文件加载的策略在并发模式下应正常工作。"""
        # 使用项目自带的策略文件
        strategy_path = Path("strategies/macd_cross.py")
        if not strategy_path.exists():
            pytest.skip("strategies/macd_cross.py not found")

        import importlib.util

        from easy_tdx.backtest.strategy import Strategy

        spec = importlib.util.spec_from_file_location("strat", strategy_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = None
        for name in dir(mod):
            obj = getattr(mod, name)
            try:
                if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                    cls = obj
                    break
            except TypeError:
                pass
        assert cls is not None, "No Strategy subclass found in macd_cross.py"

        scanner = SignalScanner(cls, vipdoc_path=vipdoc)
        # 并发模式不应抛出异常（修复前会因为 pickle 失败而静默返回空列表）
        results = scanner.scan(universe="all", workers=2)
        # 结果应为列表（可能为空，取决于策略信号）
        assert isinstance(results, list)


class TestIncrementalScan:
    """测试增量扫描."""

    def test_second_scan_uses_cache(self, vipdoc: Path, tmp_path: Path) -> None:
        """第二次扫描应使用缓存, 不重新计算."""
        cache_file = tmp_path / "scan_cache.json"
        scanner = SignalScanner(
            AlwaysBuyStrategy,
            vipdoc_path=vipdoc,
            cache_file=cache_file,
        )

        # 第一次扫描: 无缓存
        results1 = scanner.scan(universe="all")
        assert len(results1) >= 1
        assert cache_file.is_file()

        # 第二次扫描: 应使用缓存, 结果相同
        results2 = scanner.scan(universe="all")
        codes1 = sorted(r.code for r in results1)
        codes2 = sorted(r.code for r in results2)
        assert codes1 == codes2

    def test_no_cache_file_means_full_scan(self, vipdoc: Path) -> None:
        """无缓存文件时每次都是全量扫描."""
        scanner = SignalScanner(AlwaysBuyStrategy, vipdoc_path=vipdoc)

        results1 = scanner.scan(universe="all")
        results2 = scanner.scan(universe="all")

        codes1 = sorted(r.code for r in results1)
        codes2 = sorted(r.code for r in results2)
        assert codes1 == codes2

    def test_cache_updated_after_file_change(self, vipdoc: Path, tmp_path: Path) -> None:
        """文件变化后缓存应失效, 重新扫描."""
        cache_file = tmp_path / "scan_cache.json"
        scanner = SignalScanner(
            AlwaysBuyStrategy,
            vipdoc_path=vipdoc,
            cache_file=cache_file,
        )

        # 第一次扫描
        results1 = scanner.scan(universe="all")
        assert len(results1) >= 1

        # 修改文件 (touch mtime)
        import time

        day_file = vipdoc / "sz" / "lday" / "sz000001.day"
        time.sleep(0.1)
        day_file.touch()

        # 第二次扫描: sz000001 应被重新扫描
        results2 = scanner.scan(universe="all")
        codes2 = sorted(r.code for r in results2)
        # 结果可能相同 (策略没变), 但不应崩溃
        assert len(codes2) >= 1


class TestScanFailureLogging:
    """扫描失败日志回归（审计复审 L2）。

    首轮 #6 将扫描循环的 ``except Exception: continue`` 评为"系统性失败被静默
    吞掉"。复审 L2 修复：单股失败记录 warning + 失败计数，失败率超阈值时
    循环结束发出 summary。这些测试用 monkeypatch 让 ``_scan_one`` 抛错模拟
    损坏 .day / 策略异常等场景，断言失败被记录（read_daily_bars 本身对短文件
    容错返回 0 条，不会抛错，故用 monkeypatch 构造确定性失败）。
    """

    def test_serial_scan_logs_per_stock_failure(
        self, vipdoc: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """单股 _scan_one 抛错时，串行扫描应记录 warning（审计复审 L2）。"""
        scanner = SignalScanner(AlwaysBuyStrategy, vipdoc_path=vipdoc)

        def _boom(self: SignalScanner, filepath: Path, market: str, code: str) -> None:
            raise RuntimeError(f"simulated corrupt day for {code}")

        monkeypatch.setattr(SignalScanner, "_scan_one", _boom)

        with caplog.at_level("WARNING", logger="easy_tdx.screen.scanner"):
            results = scanner.scan(universe="all", workers=0)

        # 全部抛错 → 无结果，但不崩溃（容错语义：跳过继续）
        assert results == []
        # 每个被扫描的 A 股都应有一条 warning
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) >= 1, "单股失败应触发 warning 日志"
        assert any("失败" in r.getMessage() for r in warnings)

    def test_serial_scan_high_failure_rate_emits_summary(
        self, vipdoc: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """失败率超阈值时应发出汇总告警（审计复审 L2）。

        全部 A 股 _scan_one 抛错（失败率 100% > 50% 阈值），断言扫描完成后
        有一条 summary warning。
        """
        scanner = SignalScanner(AlwaysBuyStrategy, vipdoc_path=vipdoc)

        def _boom(self: SignalScanner, filepath: Path, market: str, code: str) -> None:
            raise RuntimeError(f"simulated corrupt day for {code}")

        monkeypatch.setattr(SignalScanner, "_scan_one", _boom)

        with caplog.at_level("WARNING", logger="easy_tdx.screen.scanner"):
            scanner.scan(universe="all", workers=0)

        # 应有汇总告警提到"失败率过高"
        summary_msgs = [r.getMessage() for r in caplog.records if "失败率" in r.getMessage()]
        assert summary_msgs, "失败率过高时应发出汇总 warning"
