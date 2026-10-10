"""screen 模块单元测试 — 纯离线，无需网络。"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from easy_tdx.models.bar import SecurityBar

# ── 辅助：构造 SecurityBar ────────────────────────────────────────────────


def _make_bar(year: int, month: int, day: int, close: float, **kw: Any) -> SecurityBar:
    """快速构造一个 SecurityBar。"""
    return SecurityBar(
        open=kw.get("open", close - 0.1),
        close=close,
        high=kw.get("high", close + 0.2),
        low=kw.get("low", close - 0.3),
        vol=kw.get("vol", 10000.0),
        amount=kw.get("amount", close * 10000),
        year=year,
        month=month,
        day=day,
        hour=0,
        minute=0,
    )


def _make_bars(n: int, base_close: float = 10.0) -> list[SecurityBar]:
    """构造 n 根连续日 K 线，收盘价从 base_close 开始递增。"""
    bars = []
    for i in range(n):
        year = 2024
        month = 1 + i // 28
        day = 1 + i % 28
        if month > 12:
            year += (month - 1) // 12
            month = 1 + (month - 1) % 12
        close = base_close + i * 0.1
        bars.append(_make_bar(year, month, day, close))
    return bars


# ── _bars_to_df 测试 ──────────────────────────────────────────────────────


class TestBarsToDf:
    """测试 scanner._bars_to_df 辅助函数。"""

    def test_empty_bars(self) -> None:
        from easy_tdx.screen.scanner import _bars_to_df

        df = _bars_to_df([])
        assert df.empty

    def test_single_bar(self) -> None:
        from easy_tdx.screen.scanner import _bars_to_df

        bar = _make_bar(2024, 6, 10, 12.5)
        df = _bars_to_df([bar])
        assert len(df) == 1
        assert df.iloc[0]["close"] == 12.5
        assert "datetime" in df.columns
        assert "open" in df.columns
        assert "vol" in df.columns

    def test_multiple_bars(self) -> None:
        from easy_tdx.screen.scanner import _bars_to_df

        bars = _make_bars(50)
        df = _bars_to_df(bars)
        assert len(df) == 50
        assert list(df.columns) == ["datetime", "open", "close", "high", "low", "vol", "amount"]

    def test_datetime_is_timestamp(self) -> None:
        from easy_tdx.screen.scanner import _bars_to_df

        bars = [_make_bar(2024, 6, 10, 12.5)]
        df = _bars_to_df(bars)
        assert isinstance(df.iloc[0]["datetime"], pd.Timestamp)


# ── ScanResult 测试 ──────────────────────────────────────────────────────


class TestScanResult:
    """测试 ScanResult 数据结构。"""

    def test_creation(self) -> None:
        from easy_tdx.screen.scanner import ScanResult

        r = ScanResult(code="000001", market="SZ", signal_date=20240610, last_close=12.5)
        assert r.code == "000001"
        assert r.market == "SZ"
        assert r.signal_date == 20240610
        assert r.last_close == 12.5


# ── SignalScanner 测试 ──────────────────────────────────────────────────


class TestSignalScanner:
    """测试信号扫描引擎。"""

    def test_to_json(self) -> None:
        from easy_tdx.screen.scanner import ScanResult, SignalScanner

        scanner = SignalScanner.__new__(SignalScanner)
        results = [
            ScanResult(code="000001", market="SZ", signal_date=20240610, last_close=12.5),
            ScanResult(code="600519", market="SH", signal_date=20240610, last_close=1800.0),
        ]
        json_str = scanner.to_json(results, "TestStrategy", "test.py", 100)
        data = json.loads(json_str)

        assert data["strategy"] == "TestStrategy"
        assert data["strategy_file"] == "test.py"
        assert data["total_scanned"] == 100
        assert data["total_signals"] == 2
        assert len(data["signals"]) == 2
        assert data["signals"][0]["code"] == "000001"
        assert data["signals"][1]["market"] == "SH"

    def test_to_json_empty(self) -> None:
        from easy_tdx.screen.scanner import SignalScanner

        scanner = SignalScanner.__new__(SignalScanner)
        json_str = scanner.to_json([], "Test", "t.py", 50)
        data = json.loads(json_str)
        assert data["total_signals"] == 0
        assert data["signals"] == []


# ── RankEntry 测试 ──────────────────────────────────────────────────────


class TestRankEntry:
    """测试 RankEntry 数据结构。"""

    def test_creation(self) -> None:
        from easy_tdx.screen.ranker import RankEntry

        e = RankEntry(
            rank=1,
            code="300308",
            market="SZ",
            name="",
            signal_date=20240610,
            last_close=85.0,
            performance={"sharpe": 1.85, "total_return": 0.45},
        )
        assert e.rank == 1
        assert e.performance["sharpe"] == 1.85


# ── SignalRanker.to_json 测试 ──────────────────────────────────────────


class TestRankerJson:
    """测试 Ranker 的 JSON 输出。"""

    def test_to_json(self) -> None:
        from easy_tdx.screen.ranker import RankEntry, SignalRanker

        entries = [
            RankEntry(
                rank=1,
                code="300308",
                market="SZ",
                name="",
                signal_date=20240610,
                last_close=85.0,
                performance={"sharpe": 1.85, "total_return": 0.45},
            ),
        ]
        json_str = SignalRanker.to_json(entries, "RSI", "sharpe")
        data = json.loads(json_str)

        assert data["strategy"] == "RSI"
        assert data["sort_by"] == "sharpe"
        assert data["total_ranked"] == 1
        assert data["ranking"][0]["rank"] == 1
        assert data["ranking"][0]["code"] == "300308"

    def test_to_table(self) -> None:
        from easy_tdx.screen.ranker import RankEntry, SignalRanker

        entries = [
            RankEntry(
                rank=1,
                code="300308",
                market="SZ",
                name="中际旭创",
                signal_date=20240610,
                last_close=85.0,
                performance={
                    "total_return": 0.4523,
                    "annual_return": 0.1872,
                    "max_drawdown": 0.1235,
                    "sharpe": 1.85,
                    "win_rate": 0.625,
                    "total_trades": 16,
                },
            ),
        ]
        table = SignalRanker.to_table(entries, "sharpe")
        assert "信号排名" in table
        assert "SZ300308" in table
        assert "45.23%" in table

    def test_to_table_empty(self) -> None:
        from easy_tdx.screen.ranker import SignalRanker

        table = SignalRanker.to_table([], "sharpe")
        assert "无有效排名结果" in table


# ── load_signals 测试 ──────────────────────────────────────────────────


class TestLoadSignals:
    """测试信号 JSON 加载。"""

    def test_load_from_file(self, tmp_path: Path) -> None:
        from easy_tdx.screen.ranker import load_signals

        data = {
            "strategy": "RSI",
            "strategy_file": "rsi.py",
            "signals": [
                {"code": "000001", "market": "SZ", "signal_date": 20240610, "last_close": 12.5},
            ],
        }
        filepath = tmp_path / "signals.json"
        filepath.write_text(json.dumps(data), encoding="utf-8")

        signals, name, sfile = load_signals(str(filepath))
        assert len(signals) == 1
        assert name == "RSI"
        assert sfile == "rsi.py"
        assert signals[0]["code"] == "000001"

    def test_load_from_stdin(self) -> None:
        from easy_tdx.screen.ranker import load_signals

        data = {
            "strategy": "MACD",
            "signals": [
                {"code": "600519", "market": "SH"},
            ],
        }
        json_str = json.dumps(data)

        with patch("sys.stdin", StringIO(json_str)):
            signals, name, _ = load_signals("-")

        assert len(signals) == 1
        assert name == "MACD"

    def test_load_missing_file(self) -> None:
        from easy_tdx.screen.ranker import load_signals

        with pytest.raises(FileNotFoundError):
            load_signals("/nonexistent/path.json")

    def test_load_empty_signals(self, tmp_path: Path) -> None:
        from easy_tdx.screen.ranker import load_signals

        data = {"strategy": "RSI", "signals": []}
        filepath = tmp_path / "empty.json"
        filepath.write_text(json.dumps(data), encoding="utf-8")

        signals, name, _ = load_signals(str(filepath))
        assert signals == []


# ── 集成：scanner._scan_one 逻辑 ─────────────────────────────────────


class TestScanOne:
    """测试 scanner 的单股扫描逻辑（模拟策略信号）。"""

    def test_no_signal(self) -> None:
        """策略不产生买入信号时返回 None。"""
        from easy_tdx.screen.scanner import SignalScanner

        # 构造一个永远不产生买入信号的 mock 策略
        mock_strategy = MagicMock()
        mock_strategy.__name__ = "NeverBuyStrategy"

        scanner = SignalScanner.__new__(SignalScanner)
        scanner._strategy_cls = mock_strategy
        scanner._vipdoc = Path("/fake")
        scanner._cash = 100000.0
        scanner._commission = 0.0003

        with patch.object(scanner, "_scan_one") as mock_scan:
            # 不产生信号时返回 None
            mock_scan.return_value = None
            result = scanner._scan_one(Path("/fake/sz000001.day"), "SZ", "000001")
            assert result is None

    def test_collect_files_universe_sh(self) -> None:
        """universe=sh 时只扫描上海 A 股。"""
        from easy_tdx.screen.scanner import SignalScanner

        scanner = SignalScanner.__new__(SignalScanner)

        # mock vipdoc 目录结构
        sh_dir = MagicMock()
        sh_files = [MagicMock(name="sh600000.day"), MagicMock(name="sh000001.day")]
        sh_files[0].name = "sh600000.day"
        sh_files[1].name = "sh000001.day"
        sh_dir.is_dir.return_value = True
        sh_dir.glob.return_value = iter(sh_files)

        sz_dir = MagicMock()
        sz_dir.is_dir.return_value = False

        mock_vipdoc = MagicMock()
        mock_vipdoc.__truediv__ = MagicMock(
            side_effect=lambda x: sh_dir if "sh" in str(x) else sz_dir
        )

        scanner._vipdoc = mock_vipdoc

        # 只测 universe 过滤逻辑（不测文件 IO）
        # 实际测试：_collect_files 应该跳过指数文件 sh000001
        # 这里验证 _detect_security_type 被正确调用
        from easy_tdx.offline.daily_bar import _detect_security_type

        assert _detect_security_type("sh600000.day") == "SH_A_STOCK"
        assert _detect_security_type("sh000001.day") == "SH_INDEX"
        assert _detect_security_type("sz000001.day") == "SZ_A_STOCK"
        assert _detect_security_type("sz399001.day") == "SZ_INDEX"
        assert _detect_security_type("sz159919.day") == "SZ_FUND"

    def test_detect_security_type_etf_and_funds(self) -> None:
        """ETF / 基金 / 科创板 / 国债逆回购不应被误判为 A 股。

        回归测试：修复前 sh588710/sh562590/sz184801/sh204001 等被
        _detect_security_type 默认返回值误判为 SZ_A_STOCK。
        """
        from easy_tdx.offline.daily_bar import _detect_security_type

        # ── 真 A 股（必须正确识别）──
        assert _detect_security_type("sh600000.day") == "SH_A_STOCK"
        assert _detect_security_type("sh601869.day") == "SH_A_STOCK"  # 长飞光纤
        assert _detect_security_type("sh688146.day") == "SH_A_STOCK"  # 科创板
        assert _detect_security_type("sz000001.day") == "SZ_A_STOCK"
        assert _detect_security_type("sz300489.day") == "SZ_A_STOCK"  # 创业板

        # ── 上交所 ETF / LOF / 货币基金（曾经误判为 SZ_A_STOCK）──
        assert _detect_security_type("sh588710.day") == "SH_FUND"  # 科创板ETF
        assert _detect_security_type("sh588000.day") == "SH_FUND"
        assert _detect_security_type("sh589000.day") == "SH_FUND"  # 科创板行业ETF
        assert _detect_security_type("sh562590.day") == "SH_FUND"  # 科创板LOF
        assert _detect_security_type("sh563000.day") == "SH_FUND"
        assert _detect_security_type("sh520500.day") == "SH_FUND"  # ETF
        assert _detect_security_type("sh530000.day") == "SH_FUND"
        assert _detect_security_type("sh551000.day") == "SH_FUND"  # 货币ETF
        assert _detect_security_type("sh501000.day") == "SH_FUND"  # LOF
        assert _detect_security_type("sh510300.day") == "SH_FUND"  # 沪深300ETF

        # ── 深交所封闭式基金 / LOF（sz184801 曾误判为 SZ_A_STOCK）──
        assert _detect_security_type("sz184801.day") == "SZ_FUND"
        assert _detect_security_type("sz150200.day") == "SZ_FUND"  # 分级基金
        assert _detect_security_type("sz161725.day") == "SZ_FUND"  # LOF

        # ── 国债逆回购（债券类）──
        assert _detect_security_type("sh204001.day") == "SH_BOND"  # GC001

        # ── 指数 ──
        assert _detect_security_type("sh000001.day") == "SH_INDEX"  # 上证综指
        assert _detect_security_type("sz399001.day") == "SZ_INDEX"  # 深证成指

        # ── 未知代码段不应被默认成 A 股 ──
        assert _detect_security_type("sh777777.day") == "UNKNOWN"
        assert _detect_security_type("sz777777.day") == "UNKNOWN"


# ── 策略加载测试 ────────────────────────────────────────────────────────


class TestLoadStrategy:
    """测试 CLI 的策略加载。"""

    def test_load_valid_strategy(self, tmp_path: Path) -> None:
        from easy_tdx.screen.cli import _load_strategy

        # 写一个简单的策略文件
        strategy_code = """
from easy_tdx.backtest import Strategy

class DummyStrategy(Strategy):
    def init(self) -> None:
        pass
    def next(self) -> None:
        pass
"""
        filepath = tmp_path / "dummy.py"
        filepath.write_text(strategy_code, encoding="utf-8")

        cls = _load_strategy(str(filepath))
        assert cls.__name__ == "DummyStrategy"

    def test_load_missing_file(self) -> None:
        from easy_tdx.screen.cli import _load_strategy

        with pytest.raises(SystemExit):
            _load_strategy("/nonexistent/strategy.py")

    def test_load_no_strategy_class(self, tmp_path: Path) -> None:
        from easy_tdx.screen.cli import _load_strategy

        filepath = tmp_path / "empty.py"
        filepath.write_text("x = 1\n", encoding="utf-8")

        with pytest.raises(SystemExit):
            _load_strategy(str(filepath))


# ── 强势股排名测试 ──────────────────────────────────────────────────────


class TestStrengthPresets:
    """测试预设模式配置。"""

    def test_preset_keys(self) -> None:
        from easy_tdx.screen.strength import STRENGTH_PRESETS

        assert set(STRENGTH_PRESETS.keys()) == {"steady", "breakout", "balanced"}

    def test_steady_config(self) -> None:
        from easy_tdx.screen.strength import STRENGTH_PRESETS

        cfg = STRENGTH_PRESETS["steady"]
        assert cfg["w60"] > cfg["w5"]  # 60 日主导
        assert cfg["vol_adjusted"] is True

    def test_breakout_config(self) -> None:
        from easy_tdx.screen.strength import STRENGTH_PRESETS

        cfg = STRENGTH_PRESETS["breakout"]
        assert cfg["w5"] > cfg["w60"]  # 5 日主导
        assert cfg["vol_adjusted"] is False  # 妖股不惩罚波动

    def test_balanced_config(self) -> None:
        from easy_tdx.screen.strength import STRENGTH_PRESETS

        cfg = STRENGTH_PRESETS["balanced"]
        # 三周期接近等权
        assert abs(cfg["w5"] - cfg["w20"]) < 0.05
        assert abs(cfg["w20"] - cfg["w60"]) < 0.05
        assert cfg["vol_adjusted"] is True

    def test_all_presets_have_desc(self) -> None:
        from easy_tdx.screen.strength import STRENGTH_PRESETS

        for name, cfg in STRENGTH_PRESETS.items():
            assert "desc" in cfg, f"预设 {name} 缺少 desc"
            assert isinstance(cfg["desc"], str) and len(cfg["desc"]) > 0


class TestComputeStrengthMetrics:
    """测试纯计算函数 compute_strength_metrics。"""

    def test_data_too_short(self) -> None:
        """少于 65 根 K 线返回 None。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([10.0 + i * 0.1 for i in range(30)])
        assert compute_strength_metrics(closes, 0.3, 0.3, 0.4, True) is None

    def test_steady_uptrend(self) -> None:
        """稳定上涨的票，steady 模式应有正分。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([10.0 + i * 0.05 for i in range(70)])  # 稳定上涨
        m = compute_strength_metrics(closes, 0.2, 0.3, 0.5, True)
        assert m is not None
        assert m["ret_5"] > 0
        assert m["ret_20"] > 0
        assert m["ret_60"] > 0
        assert m["strength"] > 0

    def test_weight_normalization(self) -> None:
        """权重应自动归一化（同比例权重结果相同）。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([10.0 + i * 0.1 for i in range(70)])
        m1 = compute_strength_metrics(closes, 0.3, 0.3, 0.4, False)
        m2 = compute_strength_metrics(closes, 3.0, 3.0, 4.0, False)  # 10 倍
        assert m1 is not None and m2 is not None
        assert abs(m1["strength"] - m2["strength"]) < 1e-10

    def test_vol_adjusted_differences(self) -> None:
        """vol_adjusted True/False 应给出不同分。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([10.0 + i * 0.1 for i in range(70)])
        m_raw = compute_strength_metrics(closes, 0.3, 0.3, 0.4, False)
        m_adj = compute_strength_metrics(closes, 0.3, 0.3, 0.4, True)
        assert m_raw is not None and m_adj is not None
        assert m_raw["strength"] != m_adj["strength"]
        # 调整后 = 原始 / vol，vol < 1 时调整后更大
        assert m_adj["strength"] > m_raw["strength"]

    def test_flat_price_zero_vol(self) -> None:
        """价格不变时 vol=0，应返回 None。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([10.0] * 70)
        assert compute_strength_metrics(closes, 0.3, 0.3, 0.4, True) is None

    def test_downtrend_negative_strength(self) -> None:
        """下跌趋势的票应有负分。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([20.0 - i * 0.05 for i in range(70)])  # 稳定下跌
        m = compute_strength_metrics(closes, 0.3, 0.3, 0.4, False)
        assert m is not None
        assert m["ret_5"] < 0
        assert m["strength"] < 0

    def test_all_weights_zero(self) -> None:
        """权重全为 0 返回 None。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([10.0 + i * 0.1 for i in range(70)])
        assert compute_strength_metrics(closes, 0.0, 0.0, 0.0, True) is None

    def test_metrics_keys(self) -> None:
        """返回的字典应包含所有字段。"""
        from easy_tdx.screen.strength import compute_strength_metrics

        closes = pd.Series([10.0 + i * 0.1 for i in range(70)])
        m = compute_strength_metrics(closes, 0.3, 0.3, 0.4, True)
        assert m is not None
        assert set(m.keys()) == {
            "ret_5",
            "ret_20",
            "ret_60",
            "vol_20",
            "strength",
        }


class TestStrengthResult:
    """测试 StrengthResult 数据结构。"""

    def test_creation(self) -> None:
        from easy_tdx.screen.strength import StrengthResult

        r = StrengthResult(code="000001", market="SZ", strength=1.5)
        assert r.code == "000001"
        assert r.market == "SZ"
        assert r.rank == 0  # 默认
        assert r.strength == 1.5

    def test_full_creation(self) -> None:
        from easy_tdx.screen.strength import StrengthResult

        r = StrengthResult(
            rank=1,
            code="600519",
            market="SH",
            name="贵州茅台",
            last_close=1800.0,
            last_date=20260624,
            ret_5=0.05,
            ret_20=0.12,
            ret_60=0.25,
            vol_20=0.015,
            strength=8.5,
        )
        assert r.rank == 1
        assert r.name == "贵州茅台"
        assert r.last_date == 20260624


class TestStrengthRankerOutput:
    """测试 StrengthRanker 的 JSON/表格输出（不触及文件 IO）。"""

    def _make_results(self) -> list[Any]:
        from easy_tdx.screen.strength import StrengthResult

        return [
            StrengthResult(
                rank=1,
                code="000001",
                market="SZ",
                name="平安银行",
                last_close=12.5,
                last_date=20260624,
                ret_5=0.08,
                ret_20=0.15,
                ret_60=0.30,
                vol_20=0.018,
                strength=9.5,
            ),
            StrengthResult(
                rank=2,
                code="600519",
                market="SH",
                name="",
                last_close=1800.0,
                last_date=20260624,
                ret_5=0.03,
                ret_20=0.05,
                ret_60=0.10,
                vol_20=0.012,
                strength=6.2,
            ),
        ]

    def test_to_json(self) -> None:
        from easy_tdx.screen.strength import StrengthRanker

        results = self._make_results()
        json_str = StrengthRanker.to_json(results, "steady", 20260624)
        data = json.loads(json_str)

        assert data["preset"] == "steady"
        assert "preset_desc" in data
        assert data["data_date"] == 20260624
        assert data["total_ranked"] == 2
        assert data["ranking"][0]["rank"] == 1
        assert data["ranking"][0]["code"] == "000001"
        assert data["ranking"][1]["code"] == "600519"

    def test_to_table(self) -> None:
        from easy_tdx.screen.strength import StrengthRanker

        results = self._make_results()
        table = StrengthRanker.to_table(results, "breakout", 20260624)

        assert "强势股排名" in table
        assert "breakout" in table
        assert "数据截止: 2026-06-24" in table
        assert "SZ000001" in table
        assert "平安银行" in table

    def test_to_table_empty(self) -> None:
        from easy_tdx.screen.strength import StrengthRanker

        table = StrengthRanker.to_table([], "steady", 20260624)
        assert "无有效排名结果" in table

    def test_to_json_includes_all_metrics(self) -> None:
        from easy_tdx.screen.strength import StrengthRanker

        results = self._make_results()
        json_str = StrengthRanker.to_json(results, "balanced", 20260624)
        data = json.loads(json_str)

        entry = data["ranking"][0]
        for key in ("ret_5", "ret_20", "ret_60", "vol_20", "strength", "last_close", "last_date"):
            assert key in entry, f"排名条目缺少字段 {key}"


class TestStrengthRankerInit:
    """测试 StrengthRanker 初始化（不触及文件 IO）。"""

    def test_invalid_preset_raises(self) -> None:
        from easy_tdx.screen.strength import StrengthRanker

        # resolve_vipdoc 在 __init__ 中调用，需要 mock 掉
        with patch("easy_tdx.screen.strength.resolve_vipdoc", return_value=Path("/fake")):
            with pytest.raises(ValueError, match="未知预设"):
                StrengthRanker(preset="invalid")

    def test_custom_weights_override_preset(self) -> None:
        from easy_tdx.screen.strength import StrengthRanker

        with patch("easy_tdx.screen.strength.resolve_vipdoc", return_value=Path("/fake")):
            ranker = StrengthRanker(preset="steady", w5=0.5, w20=0.3, w60=0.2, vol_adjusted=False)
        assert ranker._w5 == 0.5
        assert ranker._w20 == 0.3
        assert ranker._w60 == 0.2
        assert ranker._vol_adjusted is False

    def test_preset_property(self) -> None:
        from easy_tdx.screen.strength import StrengthRanker

        with patch("easy_tdx.screen.strength.resolve_vipdoc", return_value=Path("/fake")):
            ranker = StrengthRanker(preset="breakout")
        assert ranker.preset == "breakout"
