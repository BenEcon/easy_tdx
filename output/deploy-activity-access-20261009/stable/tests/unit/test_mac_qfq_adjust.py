"""本地前复权（QFQ）重算纯函数的单元测试。

覆盖 ``easy_tdx.mac.adjust`` 的因子计算与 OHLC 缩放，重点验证：
- 除权日前后价格连续（前复权的定义性性质）；
- 最新价锚定不动；
- 无事件 / 非法因子时安全降级。

公式见 ``examples/06_finance/xdxr_info.py`` 与 ``src/easy_tdx/mac/adjust.py``。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.mac.adjust import (
    apply_forward_adjust,
    compute_forward_factor,
    has_bad_prices,
)


def _kline(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """构造最小 NONE K 线：OHLC 全等于给定 close 序列，逐日递增。"""
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="D")
    arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": arr,
            "high": arr,
            "low": arr,
            "close": arr,
            "vol": [100.0] * n,
        }
    )


def _xdxr_one(date: str, fenhong=0.0, peigujia=0.0, songzhuangu=0.0, peigu=0.0) -> pd.DataFrame:
    """构造单条 category==1 除权除息记录。"""
    return pd.DataFrame(
        [
            {
                "date": date,
                "category": 1,
                "fenhong": fenhong,
                "peigujia": peigujia,
                "songzhuangu": songzhuangu,
                "peigu": peigu,
            }
        ]
    )


# --------------------------------------------------------------------------- #
# compute_forward_factor
# --------------------------------------------------------------------------- #


def test_factor_pure_cash_dividend():
    """纯现金分红：f = (P - fh) / P。"""
    # P=10, fh=2 → f=0.8（前复权把含权价缩到除权后等价）
    assert compute_forward_factor(10.0, 2.0, 0.0, 0.0, 0.0) == 0.8


def test_factor_songzhuangu_split():
    """10 送 10（songzhuangu=1.0）：f = P / (P*2) = 0.5。"""
    assert compute_forward_factor(10.0, 0.0, 0.0, 1.0, 0.0) == 0.5


def test_factor_zero_cum_close_is_nan():
    """cum_close<=0 返回 NaN（不抛）。"""
    assert np.isnan(compute_forward_factor(0.0, 1.0, 0.0, 0.0, 0.0))
    assert np.isnan(compute_forward_factor(-1.0, 1.0, 0.0, 0.0, 0.0))


def test_factor_zero_denominator_is_nan():
    """分母 = P*(1+s+p) 为 0 时返回 NaN。"""
    # P=10, s=-1, p=0 → denom=0
    assert np.isnan(compute_forward_factor(10.0, 0.0, 0.0, -1.0, 0.0))


# --------------------------------------------------------------------------- #
# apply_forward_adjust
# --------------------------------------------------------------------------- #


def test_apply_pure_cash_dividend_scales_pre_event_only():
    """纯分红：除权日及之前价格乘 f，除权日之后不动。"""
    # 3 根：cum-div close=10（含权），ex-date close=8（跌去 2 元分红），之后 9
    # 事件在 day2（ex-date），cum-div bar 是 day1
    df = _kline([10.0, 10.0, 8.0, 9.0])
    xd = _xdxr_one("2024-01-03", fenhong=2.0)  # ex-date = 第 3 天
    out = apply_forward_adjust(df, xd)
    # f = (10-2)/10 = 0.8 → day1/day2 (cum 及之前) *= 0.8
    assert out["close"].tolist() == [8.0, 8.0, 8.0, 9.0]


def test_apply_latest_price_anchored():
    """最新价（最后一根）不被缩放，保持原值。"""
    df = _kline([20.0, 10.0, 11.0])
    xd = _xdxr_one("2024-01-02", fenhong=10.0)  # ex-date=day2, cum-div=day1 close=20
    out = apply_forward_adjust(df, xd)
    # f=(20-10)/20=0.5 → day1*=0.5; day2/day3 不动
    assert out["close"].iloc[-1] == 11.0
    assert out["close"].iloc[0] == 10.0


def test_apply_no_events_returns_unchanged():
    """空 XDXR 或无 category==1 → 原样返回（值相等）。"""
    df = _kline([10.0, 11.0, 12.0])
    out = apply_forward_adjust(df, pd.DataFrame(columns=["date", "category"]))
    assert out["close"].tolist() == [10.0, 11.0, 12.0]


def test_apply_empty_xdxr_df():
    """XDXR 为 None 或 empty → 原样返回。"""
    df = _kline([10.0, 11.0])
    assert apply_forward_adjust(df, pd.DataFrame()).equals(df)
    assert apply_forward_adjust(df, None).equals(df)  # type: ignore[arg-type]


def test_apply_nan_factor_event_skipped():
    """事件对应 cum_close<=0（因子非法）→ 跳过该事件，不抛异常。"""
    # day1 close=0（非法 cum-div），事件在 day2
    df = _kline([0.0, 5.0, 6.0])
    xd = _xdxr_one("2024-01-02", fenhong=1.0)
    out = apply_forward_adjust(df, xd)  # 不应抛
    # cum-div bar (day1) close=0 → 因子 NaN → 跳过，close 不变
    assert out["close"].tolist() == [0.0, 5.0, 6.0]


def test_apply_multiple_events_cumulative():
    """两次连续分红：因子累乘。"""
    # day1=20(cum1), day2 ex-date1, day3=12(cum2), day4 ex-date2, day5=10
    df = _kline([20.0, 18.0, 12.0, 10.0, 10.0])
    xd = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "category": 1,
                "fenhong": 2.0,
                "peigujia": 0.0,
                "songzhuangu": 0.0,
                "peigu": 0.0,
            },
            {
                "date": "2024-01-04",
                "category": 1,
                "fenhong": 2.0,
                "peigujia": 0.0,
                "songzhuangu": 0.0,
                "peigu": 0.0,
            },
        ]
    )
    out = apply_forward_adjust(df, xd)
    # event1: cum1=day1=20, f1=(20-2)/20=0.9 → day1*=0.9 → 18.0
    # event2: cum2=day3=12, f2=(12-2)/12=0.8333 → day1..day3 *= 0.8333
    #   day1: 18.0 * 0.8333 = 15.0 ; day3: 12.0*0.8333=10.0
    # day4/day5 不动
    assert round(out["close"].iloc[0], 4) == 15.0
    assert round(out["close"].iloc[2], 4) == 10.0
    assert out["close"].iloc[3] == 10.0
    assert out["close"].iloc[4] == 10.0


def test_apply_songzhuangu_halves_pre_event_prices():
    """10 送 10：除权日前价格减半。"""
    df = _kline([20.0, 20.0, 10.0, 11.0])
    xd = _xdxr_one("2024-01-03", songzhuangu=1.0)
    out = apply_forward_adjust(df, xd)
    # cum-div=day2=20, f=20/(20*2)=0.5 → day1/day2 *= 0.5
    assert out["close"].tolist() == [10.0, 10.0, 10.0, 11.0]


def test_apply_does_not_mutate_input():
    """apply_forward_adjust 不就地修改输入 DataFrame。"""
    df = _kline([10.0, 10.0, 8.0])
    original = df["close"].tolist()
    xd = _xdxr_one("2024-01-03", fenhong=2.0)
    apply_forward_adjust(df, xd)
    assert df["close"].tolist() == original


# --------------------------------------------------------------------------- #
# has_bad_prices
# --------------------------------------------------------------------------- #


def test_has_bad_prices_detects_negative():
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [-0.5], "close": [1.0]})
    assert has_bad_prices(df) is True


def test_has_bad_prices_detects_zero():
    df = pd.DataFrame({"open": [0.0], "high": [1.0], "low": [1.0], "close": [1.0]})
    assert has_bad_prices(df) is True


def test_has_bad_prices_detects_nan():
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [float("nan")]})
    assert has_bad_prices(df) is True


def test_has_bad_prices_clean_returns_false():
    df = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]})
    assert has_bad_prices(df) is False
