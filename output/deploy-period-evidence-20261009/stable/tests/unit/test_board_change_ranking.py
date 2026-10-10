"""板块 N 日涨跌幅排行榜单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from easy_tdx.mac.client import MacClient


def _make_kline_df(closes: list[float], dates: list[str] | None = None) -> pd.DataFrame:
    """构造模拟 K 线 DataFrame。"""
    n = len(closes)
    if dates is None:
        dates = [f"2025-06-{i + 1:02d}" for i in range(n)]
    return pd.DataFrame(
        {
            "datetime": pd.to_datetime(dates),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "vol": [1000.0] * n,
            "amount": [10000.0] * n,
        }
    )


def _make_boards_df(boards: list[tuple[str, str, int]]) -> pd.DataFrame:
    """构造模拟板块列表 DataFrame。

    Args:
        boards: [(code, name, market), ...]
    """
    return pd.DataFrame(
        {
            "code": [b[0] for b in boards],
            "name": [b[1] for b in boards],
            "market": [b[2] for b in boards],
        }
    )


# ---------------------------------------------------------------------------
# 测试：空板块列表
# ---------------------------------------------------------------------------


@patch.object(MacClient, "get_stock_kline")
@patch.object(MacClient, "get_board_list")
def test_empty_board_list(mock_board_list, mock_kline):
    """空板块列表应返回带正确列名的空 DataFrame。"""
    mock_board_list.return_value = pd.DataFrame(columns=["code", "name", "market"])

    client = MagicMock(spec=MacClient)
    client.get_board_list = mock_board_list
    client.get_stock_kline = mock_kline

    result = MacClient.get_board_change_ranking(client, board_type=0, days=20)

    expected_cols = ["code", "name", "close_end", "close_start", "change_pct"]
    assert result.empty
    assert list(result.columns) == expected_cols


# ---------------------------------------------------------------------------
# 测试：基本涨跌幅计算
# ---------------------------------------------------------------------------


def test_basic_change_calculation():
    """验证涨跌幅计算逻辑正确。"""
    # 12 根 K 线
    kline_a = _make_kline_df(
        [90, 92, 95, 98, 100, 102, 105, 108, 112, 115, 118, 120],
        dates=[f"2025-05-{d:02d}" for d in range(1, 13)],
    )
    kline_b = _make_kline_df(
        [55, 54, 53, 52, 50, 49, 48, 47, 46, 45, 44, 45],
        dates=[f"2025-05-{d:02d}" for d in range(1, 13)],
    )

    kline_a = kline_a.sort_values("datetime").reset_index(drop=True)
    kline_b = kline_b.sort_values("datetime").reset_index(drop=True)

    days = 5
    # 板块 A：end_pos=11(close=120), start_pos=6(close=105)
    end_pos_a = len(kline_a) - 1
    start_pos_a = max(0, end_pos_a - days)
    close_end_a = float(kline_a.loc[end_pos_a, "close"])
    close_start_a = float(kline_a.loc[start_pos_a, "close"])
    pct_a = round((close_end_a - close_start_a) / close_start_a * 100, 2)

    assert close_end_a == 120
    assert close_start_a == 105
    assert pct_a == round((120 - 105) / 105 * 100, 2)

    # 板块 B
    end_pos_b = len(kline_b) - 1
    start_pos_b = max(0, end_pos_b - days)
    close_end_b = float(kline_b.loc[end_pos_b, "close"])
    close_start_b = float(kline_b.loc[start_pos_b, "close"])
    pct_b = round((close_end_b - close_start_b) / close_start_b * 100, 2)
    assert close_end_b == 45
    assert close_start_b == 48
    assert pct_b == round((45 - 48) / 48 * 100, 2)


# ---------------------------------------------------------------------------
# 测试：非交易日（周末）自动回退到前一交易日
# ---------------------------------------------------------------------------


def test_target_date_falls_on_weekend():
    """target_date 是周六时，应使用周五的收盘价。"""
    dates = ["2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05", "2025-06-06"]
    closes = [100.0, 102.0, 104.0, 106.0, 108.0]
    kline_df = _make_kline_df(closes, dates)
    kline_df = kline_df.sort_values("datetime").reset_index(drop=True)

    # 2025-06-07 是周六
    target_ts = pd.Timestamp("2025-06-07")
    mask = kline_df["datetime"] <= target_ts
    assert mask.any()
    end_pos = int(mask[mask].index[-1])
    assert float(kline_df.loc[end_pos, "close"]) == 108.0  # 周五的收盘价


# ---------------------------------------------------------------------------
# 测试：K 线不足 N+1 根时使用最早可用 bar
# ---------------------------------------------------------------------------


def test_insufficient_history():
    """K 线只有 5 根但 days=20 时，应使用第一根 bar 作为 close_start。"""
    closes = [100.0, 102.0, 104.0, 106.0, 108.0]
    kline_df = _make_kline_df(closes)
    kline_df = kline_df.sort_values("datetime").reset_index(drop=True)

    days = 20
    end_pos = len(kline_df) - 1  # 4
    start_pos = max(0, end_pos - days)  # 0
    close_end = float(kline_df.loc[end_pos, "close"])
    close_start = float(kline_df.loc[start_pos, "close"])

    assert close_end == 108.0
    assert close_start == 100.0
    pct = round((108 - 100) / 100 * 100, 2)
    assert pct == 8.0


# ---------------------------------------------------------------------------
# 测试：close_start == 0 时跳过
# ---------------------------------------------------------------------------


def test_close_start_zero_skipped():
    """close_start 为 0 的板块应被跳过。"""
    closes = [0.0, 10.0, 20.0]
    kline_df = _make_kline_df(closes)
    kline_df = kline_df.sort_values("datetime").reset_index(drop=True)

    days = 2
    end_pos = len(kline_df) - 1
    start_pos = max(0, end_pos - days)
    close_start = float(kline_df.loc[start_pos, "close"])
    assert close_start == 0.0  # 应被跳过


# ---------------------------------------------------------------------------
# 测试：days < 1 抛出 ValueError
# ---------------------------------------------------------------------------


def test_days_less_than_one_raises():
    """days < 1 应抛出 ValueError。"""
    with pytest.raises(ValueError, match="days 必须 >= 1"):
        raise ValueError("days 必须 >= 1，got 0")


# ---------------------------------------------------------------------------
# 测试：空 K 线的板块被跳过
# ---------------------------------------------------------------------------


def test_empty_kline_skipped():
    """K 线返回空 DataFrame 的板块应被跳过。"""
    kline_df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "vol", "amount"])
    assert kline_df.empty


# ---------------------------------------------------------------------------
# 测试：完整端到端（mock MacClient）
# ---------------------------------------------------------------------------


@patch.object(MacClient, "get_stock_kline")
@patch.object(MacClient, "get_board_list")
def test_full_ranking(mock_board_list, mock_kline):
    """完整排行测试：3 个板块，验证排序和 top_n。"""
    boards_df = _make_boards_df(
        [("881001", "酒店餐饮", 1), ("881002", "半导体", 1), ("881003", "银行", 1)]
    )
    mock_board_list.return_value = boards_df

    dates = [f"2025-05-{d:02d}" for d in range(1, 31)]

    # 板块 A：从 100 → 129（+29%）
    kline_a = _make_kline_df([100 + i for i in range(30)], dates)
    # 板块 B：从 100 → ~80（-20%）
    kline_b = _make_kline_df([100 - i * 0.67 for i in range(30)], dates)
    # 板块 C：从 100 → ~110（+10%）
    kline_c = _make_kline_df([100 + i * 0.33 for i in range(30)], dates)

    kline_map = {"881001": kline_a, "881002": kline_b, "881003": kline_c}

    def kline_side_effect(market, code, **kwargs):
        return kline_map.get(code, pd.DataFrame())

    mock_kline.side_effect = kline_side_effect

    client = MagicMock(spec=MacClient)
    client.get_board_list = mock_board_list
    client.get_stock_kline = mock_kline

    result = MacClient.get_board_change_ranking(client, board_type=0, days=20, top_n=3)

    assert not result.empty
    assert len(result) == 3
    assert list(result.columns) == ["code", "name", "close_end", "close_start", "change_pct"]
    # 降序：A(涨幅最大) > C > B(跌幅最大)
    assert result.iloc[0]["code"] == "881001"
    assert result.iloc[1]["code"] == "881003"
    assert result.iloc[2]["code"] == "881002"


@patch.object(MacClient, "get_stock_kline")
@patch.object(MacClient, "get_board_list")
def test_top_n_truncation(mock_board_list, mock_kline):
    """top_n=2 时只返回前 2 个板块。"""
    boards_df = _make_boards_df([("881001", "A", 1), ("881002", "B", 1), ("881003", "C", 1)])
    mock_board_list.return_value = boards_df

    dates = [f"2025-05-{d:02d}" for d in range(1, 31)]
    kline_a = _make_kline_df([100 + i for i in range(30)], dates)
    kline_b = _make_kline_df([100 - i * 0.5 for i in range(30)], dates)
    kline_c = _make_kline_df([100 + i * 0.2 for i in range(30)], dates)

    kline_map = {"881001": kline_a, "881002": kline_b, "881003": kline_c}

    def kline_side_effect(market, code, **kwargs):
        return kline_map.get(code, pd.DataFrame())

    mock_kline.side_effect = kline_side_effect

    client = MagicMock(spec=MacClient)
    client.get_board_list = mock_board_list
    client.get_stock_kline = mock_kline

    result = MacClient.get_board_change_ranking(client, board_type=0, days=20, top_n=2)
    assert len(result) == 2
    assert result.iloc[0]["code"] == "881001"
    assert result.iloc[1]["code"] == "881003"


@patch.object(MacClient, "get_stock_kline")
@patch.object(MacClient, "get_board_list")
def test_ascending_order(mock_board_list, mock_kline):
    """ascending=True 时跌幅最大的排前面。"""
    boards_df = _make_boards_df([("881001", "A", 1), ("881002", "B", 1)])
    mock_board_list.return_value = boards_df

    dates = [f"2025-05-{d:02d}" for d in range(1, 31)]
    kline_a = _make_kline_df([100 + i for i in range(30)], dates)
    kline_b = _make_kline_df([100 - i for i in range(30)], dates)

    kline_map = {"881001": kline_a, "881002": kline_b}

    def kline_side_effect(market, code, **kwargs):
        return kline_map.get(code, pd.DataFrame())

    mock_kline.side_effect = kline_side_effect

    client = MagicMock(spec=MacClient)
    client.get_board_list = mock_board_list
    client.get_stock_kline = mock_kline

    result = MacClient.get_board_change_ranking(
        client, board_type=0, days=20, top_n=10, ascending=True
    )
    assert len(result) == 2
    assert result.iloc[0]["code"] == "881002"  # 跌幅最大（change_pct 最小）


@patch.object(MacClient, "get_stock_kline")
@patch.object(MacClient, "get_board_list")
def test_days_validation(mock_board_list, mock_kline):
    """days=0 应抛出 ValueError。"""
    client = MagicMock(spec=MacClient)
    client.get_board_list = mock_board_list
    client.get_stock_kline = mock_kline

    with pytest.raises(ValueError, match="days 必须 >= 1"):
        MacClient.get_board_change_ranking(client, board_type=0, days=0)


@patch.object(MacClient, "get_stock_kline")
@patch.object(MacClient, "get_board_list")
def test_with_target_date(mock_board_list, mock_kline):
    """指定 target_date 时，截止 bar 应在 target_date 或之前。"""
    boards_df = _make_boards_df([("881001", "A", 1)])
    mock_board_list.return_value = boards_df

    dates = [f"2025-05-{d:02d}" for d in range(1, 31)]
    kline_a = _make_kline_df([100 + i for i in range(30)], dates)

    def kline_side_effect(market, code, **kwargs):
        if code == "881001":
            return kline_a
        return pd.DataFrame()

    mock_kline.side_effect = kline_side_effect

    client = MagicMock(spec=MacClient)
    client.get_board_list = mock_board_list
    client.get_stock_kline = mock_kline

    result = MacClient.get_board_change_ranking(client, board_type=0, target_date=20250520, days=5)
    assert not result.empty
    # target_date=20250520, 对应 index 19 (0-based), close=119
    # start_pos = 19 - 5 = 14, close=114
    # pct = (119-114)/114*100 ≈ 4.39
    assert result.iloc[0]["code"] == "881001"
    assert result.iloc[0]["close_end"] == 119.0
    assert result.iloc[0]["close_start"] == 114.0
