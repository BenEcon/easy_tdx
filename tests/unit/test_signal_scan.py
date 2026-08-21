"""信号雷达（signal_scan）单元 + 端到端测试（离线，无网络）。

覆盖：
- normalize_symbol 市场前缀纠错
- expand_targets 三种 kind 展开 + 数据损坏容错
- fetch_scan_bars 去重取数 / 失败容错 / date→datetime 列归一化
- evaluate_signals 金叉买入、死叉卖出、仓位跟踪、窗口过滤（与回测引擎同口径）
- run_scan 单行失败不中断 + 汇总计数
- POST /backtest/signal-scan/run/async 端到端（fake store + fake 行情）
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi")

from easy_tdx.web.signal_scan import (  # noqa: E402
    evaluate_signals,
    expand_targets,
    fetch_scan_bars,
    normalize_symbol,
    run_scan,
)
from easy_tdx.web.strategy_store import SavedStrategy  # noqa: E402

# ── 测试数据 ───────────────────────────────────────────────────────────────────


def v_shape_df(n_fall: int = 40, n_rise: int = 80, n_drop: int = 0) -> pd.DataFrame:
    """V 型走势合成日线：下跌 → 上涨（→ 可选急跌），保证出现金叉（→ 死叉）。

    返回的 df 带标准 OHLCV + datetime 列（日线接口返回 date，归一化后是 datetime）。
    """
    closes = np.concatenate(
        [
            10.0 - np.arange(n_fall) * 0.02,  # 缓跌：MA5 持续低于 MA20
            9.2 + np.arange(n_rise) * 0.12,  # 稳定上涨：金叉出现
            (10.0 + n_rise * 0.12 - np.arange(1, n_drop + 1) * 0.5) if n_drop else [],  # 急跌：死叉
        ]
    )
    n = len(closes)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": closes - 0.05,
            "high": closes + 0.10,
            "low": closes - 0.10,
            "close": closes,
            "vol": np.full(n, 5000.0),
            "amount": closes * 5000,
        }
    )


def _single(**ctx_overrides: object) -> SavedStrategy:
    ctx: dict = {"symbol": "SH:601088", "category": "DAY"}
    ctx.update(ctx_overrides)
    return SavedStrategy(
        id="s1",
        name="神华·双均线",
        kind="single",
        strategy="ma_cross",
        strategy_label="双均线交叉",
        params={"fast": 5, "slow": 20},
        context=ctx,
    )


class FakeClient:
    """假行情客户端：按 (market, code) 返回预置 df，未预置的抛错。"""

    def __init__(self, data: dict[str, pd.DataFrame]) -> None:
        self.data = data
        self.calls: list[tuple[str, str]] = []

    async def get_security_bars(self, market, code, category, start, count):  # noqa: ANN001
        market_str = str(getattr(market, "name", market))
        key = f"{market_str}:{code}"
        self.calls.append((key, str(getattr(category, "name", category))))
        if key not in self.data:
            raise ConnectionError(f"no data for {key}")
        return self.data[key]


# ── normalize_symbol ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SH:601088", "SH:601088"),  # 正确的沪市主板
        ("SZ:515080", "SH:515080"),  # 历史错标的沪市基金 → 纠正
        ("510300", "SH:510300"),  # 无前缀 → 补全
        ("SZ:000001", "SZ:000001"),  # 正确的深市主板
        ("430047", "BJ:430047"),  # 北交所
        ("830799", "BJ:830799"),  # 北交所 8xx
        ("SZ:300347", "SZ:300347"),  # 创业板
    ],
)
def test_normalize_symbol(raw: str, expected: str) -> None:
    assert normalize_symbol(raw) == expected


# ── expand_targets ────────────────────────────────────────────────────────────


def test_expand_single() -> None:
    targets = expand_targets([_single()])
    assert len(targets) == 1
    t = targets[0]
    assert (t.strategy, t.params, t.symbol, t.category) == (
        "ma_cross",
        {"fast": 5, "slow": 20},
        "SH:601088",
        "DAY",
    )
    assert t.error is None


def test_expand_portfolio_multi_symbols() -> None:
    rec = SavedStrategy(
        id="p1",
        name="银行组合",
        kind="portfolio",
        strategy="macd",
        params={"short": 10, "long": 20},
        context={"stocks": ["SZ:000001", "515080", "SH:601088"], "category": "DAY"},
    )
    targets = expand_targets([rec])
    assert len(targets) == 3
    assert [t.symbol for t in targets] == ["SZ:000001", "SH:515080", "SH:601088"]
    assert all(t.strategy == "macd" for t in targets)


def test_expand_multi_items() -> None:
    rec = SavedStrategy(
        id="m1",
        name="老登+小登组合",
        kind="multi",
        strategy="multi",
        context={
            "items": [
                {"strategy": "trix", "params": {"m1": 18, "m2": 20}, "symbol": "SZ:300347"},
                {
                    "strategy": "ema_cross",
                    "params": {"fast": 12},
                    "symbol": "SZ:301308",
                    "category": "DAY",
                },
                {"strategy": "macd", "symbol": "SH:601088"},  # 缺 params → 默认空
                {"strategy": "", "symbol": "SZ:000001"},  # 缺 strategy → error 行
            ]
        },
    )
    targets = expand_targets([rec])
    assert len(targets) == 4
    ok = [t for t in targets if t.error is None]
    assert [t.strategy for t in ok] == ["trix", "ema_cross", "macd"]
    assert ok[1].params == {"fast": 12}
    assert [t.error is None for t in targets] == [True, True, True, False]


def test_expand_error_rows() -> None:
    # single 缺 symbol / multi 缺 items → 各展开为一条 error 行（不丢策略身份）
    no_symbol = _single()
    no_symbol.context = {"category": "DAY"}
    broken_multi = SavedStrategy(id="m2", name="坏组合", kind="multi", strategy="multi")
    targets = expand_targets([no_symbol, broken_multi])
    assert len(targets) == 2
    assert all(t.error for t in targets)
    assert [t.strategy_name for t in targets] == ["神华·双均线", "坏组合"]


# ── fetch_scan_bars ───────────────────────────────────────────────────────────


def test_fetch_scan_bars_dedupe_and_normalize() -> None:
    df = v_shape_df()
    # 日线接口风格：date 列而非 datetime
    daily = df.rename(columns={"datetime": "date"})
    client = FakeClient({"SH:601088": daily, "SZ:000001": daily})
    rec1 = _single()
    rec2 = _single(id="s2", name="另一个神华", strategy="macd", params={})
    targets = expand_targets([rec1, rec2])  # 同 symbol 只取一次
    targets.append(expand_targets([_single(symbol="SZ:000001")])[0])

    bars = asyncio.run(fetch_scan_bars(client, targets))
    assert set(bars) == {("SH:601088", "DAY"), ("SZ:000001", "DAY")}
    # SH:601088 只取了一次（去重生效）
    assert len([c for c in client.calls if c[0] == "SH:601088"]) == 1
    # date 列已归一化为 datetime 且按时间正序
    out = bars[("SH:601088", "DAY")]
    assert "datetime" in out.columns
    assert out["datetime"].is_monotonic_increasing


def test_fetch_scan_bars_failure_tolerant() -> None:
    client = FakeClient({})  # 全部抛错
    targets = expand_targets([_single()])
    bars = asyncio.run(fetch_scan_bars(client, targets))
    assert bars == {("SH:601088", "DAY"): None}


# ── evaluate_signals ──────────────────────────────────────────────────────────


def _ma_cross_instance():  # noqa: ANN202
    from easy_tdx.backtest.strategies import get_registry

    return get_registry().get("ma_cross").build({"fast": 5, "slow": 20})


def _expected_cross_dates(df: pd.DataFrame, direction: str) -> list[str]:
    """用 MyTT 独立算出金叉/死叉所在日期（作为期望值，与被测代码解耦）。"""
    from easy_tdx.MyTT import CROSS, MA

    close = df["close"].to_numpy()
    fast, slow = MA(close, 5), MA(close, 20)
    mask = CROSS(fast, slow) if direction == "BUY" else CROSS(slow, fast)
    return [str(df["datetime"].iloc[i])[:16] for i in range(len(df)) if mask[i]]


def test_evaluate_signals_golden_cross_buy() -> None:
    df = v_shape_df(n_rise=30)  # 只涨不跌：恰好一个金叉、之后无死叉
    buy_dates = _expected_cross_dates(df, "BUY")
    assert len(buy_dates) == 1, "V 型数据应恰好产生一个金叉"
    cross_date = buy_dates[0]
    cross_idx = [i for i in range(len(df)) if str(df["datetime"].iloc[i])[:16] == cross_date][0]

    # 窗口恰好从金叉那根开始 → 窗口内能捕获 BUY
    result = evaluate_signals(_ma_cross_instance(), df, window=len(df) - cross_idx)
    buys = [s for s in result["recent_signals"] if s["direction"] == "BUY"]
    assert [s["date"] for s in buys] == [cross_date]
    assert result["latest_signal"] == "BUY"
    assert result["signal_date"] == cross_date
    assert result["position"] == "holding"  # 买入后一直持有
    assert result["last_close"] == pytest.approx(float(df["close"].iloc[-1]))
    assert result["last_bar_date"] == str(df["datetime"].iloc[-1])[:16]

    # 窗口再收窄一根（金叉在窗口外）→ 不上报旧信号，但仓位跟踪不受窗口影响
    result2 = evaluate_signals(_ma_cross_instance(), df, window=len(df) - cross_idx - 1)
    assert result2["recent_signals"] == []
    assert result2["latest_signal"] is None
    assert result2["position"] == "holding"


def test_evaluate_signals_death_cross_sell() -> None:
    df = v_shape_df(n_drop=15)  # 涨完急跌：金叉买入 → 死叉卖出
    result = evaluate_signals(_ma_cross_instance(), df, window=len(df))
    dirs = [s["direction"] for s in result["recent_signals"]]
    assert dirs[0] == "BUY"
    assert dirs[-1] == "SELL"
    assert result["latest_signal"] == "SELL"
    assert result["position"] == "flat"  # 清仓


def test_evaluate_signals_matches_engine_trades() -> None:
    """与真实回测引擎成交方向序列一致性抽查（同 df、同策略）。"""
    from easy_tdx.backtest.engine import BacktestEngine

    df = v_shape_df(n_drop=15)
    strat = _ma_cross_instance()
    result = evaluate_signals(strat, df, window=len(df))
    engine = BacktestEngine(strategy=_ma_cross_instance())
    trades = engine.run(df).trades
    engine_dirs = list(trades["direction"])
    scan_dirs = [s["direction"] for s in result["recent_signals"]]
    assert scan_dirs == engine_dirs[: len(scan_dirs)]


# ── run_scan ──────────────────────────────────────────────────────────────────


def test_run_scan_summary_and_errors() -> None:
    df = v_shape_df()
    targets = [
        expand_targets([_single()])[0],  # 正常行（有行情）
        expand_targets([_single(id="s2", name="同标的第二策略")])[0],  # 同标的复用行情
    ]
    # 制造三类失败：未知策略 / 无行情 / 展开错误
    bad_strategy = expand_targets([_single()])[0]
    bad_strategy.strategy = "nope_strategy"
    targets.append(bad_strategy)
    no_bars = expand_targets([_single()])[0]
    no_bars.symbol = "SZ:999999"
    targets.append(no_bars)
    broken = expand_targets([SavedStrategy(id="x", name="坏", kind="single", strategy="ma_cross")])[
        0
    ]
    targets.append(broken)

    bars = {("SH:601088", "DAY"): df}
    out = run_scan(bars, targets, window=len(df))
    assert out["total"] == 5
    assert out["buy_count"] == 2  # 前两行各有一个金叉买入
    assert out["sell_count"] == 0
    assert out["error_count"] == 3  # 未知策略 / 无行情 / 展开错误
    rows = out["rows"]
    assert rows[0]["error"] is None
    assert rows[0]["latest_signal"] == "BUY"
    assert "未知策略" in rows[2]["error"]
    assert "未取到有效 K 线" in rows[3]["error"]
    assert "缺少标的上下文" in rows[4]["error"]
    assert out["elapsed"] >= 0


# ── API 端到端 ────────────────────────────────────────────────────────────────


@pytest.fixture()
def api_client():
    from fastapi.testclient import TestClient

    from easy_tdx.web import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_signal_scan_endpoint_e2e(api_client, monkeypatch) -> None:
    """POST 提交 → 轮询 done → 结果结构完整（fake store + fake 取数）。"""
    import easy_tdx.web.signal_scan as sigscan
    import easy_tdx.web.strategy_store as store_mod

    # 缓跌 59 根 + 末根跳涨：金叉恰好发生在最后一根 K 线（窗口=1 也能捕获）
    df = v_shape_df(n_fall=59, n_rise=0)
    df.loc[df.index[-1], ["open", "high", "low", "close"]] = [14.95, 15.2, 14.8, 15.0]

    class FakeStore:
        def list_all(self) -> list[SavedStrategy]:
            return [_single()]

    async def fake_fetch(client, targets):  # noqa: ANN001
        return {("SH:601088", "DAY"): df}

    monkeypatch.setattr(store_mod, "get_store", lambda: FakeStore())
    monkeypatch.setattr(sigscan, "fetch_scan_bars", fake_fetch)

    resp = api_client.post("/api/v1/backtest/signal-scan/run/async", json={"window_bars": 1})
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]

    final = None
    for _ in range(200):
        poll = api_client.get(f"/api/v1/backtest/tasks/{task_id}")
        assert poll.status_code == 200
        final = poll.json()
        if final["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert final is not None and final["status"] == "done", final

    result = final["result"]
    assert result["total"] == 1
    assert result["buy_count"] == 1
    row = result["rows"][0]
    assert row["strategy"] == "ma_cross"
    assert row["symbol"] == "SH:601088"
    assert row["error"] is None
    assert row["position"] in ("holding", "flat")


def test_signal_scan_endpoint_empty_store(api_client, monkeypatch) -> None:
    import easy_tdx.web.strategy_store as store_mod

    class EmptyStore:
        def list_all(self) -> list[SavedStrategy]:
            return []

    monkeypatch.setattr(store_mod, "get_store", lambda: EmptyStore())
    resp = api_client.post("/api/v1/backtest/signal-scan/run/async", json={})
    assert resp.status_code == 400
    assert "策略库为空" in resp.json()["detail"]


def test_signal_scan_endpoint_window_validation(api_client) -> None:
    resp = api_client.post("/api/v1/backtest/signal-scan/run/async", json={"window_bars": 0})
    assert resp.status_code == 422
