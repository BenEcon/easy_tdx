"""Raw-row identity and transactional updates are prerequisites for causal signals."""
import pandas as pd
import pytest

from easy_tdx.chanlun import ChanlunAnalyser


def frame(size=60):
    prices = [30 + (i % 12 if i % 24 < 12 else 12 - i % 12) for i in range(size)]
    return pd.DataFrame({'datetime': pd.date_range('2026-01-01', periods=size),
                         'open': prices, 'close': prices,
                         'high': [p + 1 for p in prices], 'low': [p - 1 for p in prices],
                         'vol': [100] * size})


@pytest.mark.parametrize('alias', ['datetime', 'date'])
def test_historical_corrections_keep_chronology_and_match_clean_rebuild(alias):
    original = frame()
    analyser = ChanlunAnalyser()
    previous = analyser.process_klines(original)
    previous_snapshot = previous.to_dict()
    incoming = original.iloc[[20, 5]].copy()
    incoming.loc[:, 'vol'] = [500, 600]
    for column in ('open', 'close', 'high', 'low'):
        incoming[column] += 2
    incoming['datetime'] = incoming['datetime'].dt.strftime('%Y-%m-%d')
    incoming = incoming.rename(columns={'datetime': alias})
    result = analyser.append_klines(incoming)
    expected_frame = original.copy()
    expected_frame.loc[[20, 5], ['open', 'close', 'high', 'low']] += 2
    expected_frame.loc[[20, 5], 'vol'] = [500, 600]
    expected = ChanlunAnalyser().process_klines(expected_frame)
    assert result.to_dict() == expected.to_dict()
    assert [(b.date, b.open, b.amount) for b in result.klines] == [
        (b.date, b.open, b.amount) for b in expected.klines]
    assert [b.index for b in result.klines] == list(range(60))
    assert previous.to_dict() == previous_snapshot
    pd.testing.assert_frame_equal(original, frame())


def test_append_fills_missing_history_and_latest_duplicate_wins():
    original = frame()
    analyser = ChanlunAnalyser()
    analyser.process_klines(original.drop(index=[4, 5]))
    incoming = pd.concat([original.iloc[[5, 4]], original.iloc[[4]]], ignore_index=True)
    incoming.loc[2, 'vol'] = 700
    result = analyser.append_klines(incoming)
    expected = original.copy()
    expected.loc[4, 'vol'] = 700
    assert result.to_dict() == ChanlunAnalyser().process_klines(expected).to_dict()
    assert result.klines[4].amount == 700


@pytest.mark.parametrize('case', ['missing_time', 'bad_time', 'numeric_time', 'timezone',
                                  'missing_column', 'duplicate_column', 'nan', 'inf',
                                  'inverted_range', 'negative_volume', 'unsorted', 'duplicate'])
def test_reject_bad_batch_without_poisoning_previous_snapshot(case):
    analyser = ChanlunAnalyser()
    previous = analyser.process_klines(frame())
    original = frame(4)
    if case == 'missing_time':
        original.loc[1, 'datetime'] = pd.NaT
    elif case in ('bad_time', 'numeric_time', 'timezone'):
        original['datetime'] = original['datetime'].astype(object)
        original.loc[1, 'datetime'] = {'bad_time': 'invalid', 'numeric_time': 123,
                                        'timezone': pd.Timestamp('2026-01-02', tz='UTC')}[case]
    elif case == 'missing_column':
        original = original.drop(columns='high')
    elif case == 'duplicate_column':
        original = pd.concat([original, original[['high']]], axis=1)
    elif case in ('nan', 'inf'):
        original['close'] = original['close'].astype(float)
        original.loc[1, 'close'] = float(case)
    elif case == 'inverted_range':
        original.loc[1, 'high'] = 0
    elif case == 'negative_volume':
        original.loc[1, 'vol'] = -1
    elif case == 'unsorted':
        original = original.iloc[::-1]
    elif case == 'duplicate':
        original.loc[1, 'datetime'] = original.loc[0, 'datetime']
    with pytest.raises(ValueError):
        analyser.process_klines(original)
    assert analyser.result is previous
    assert analyser.append_klines(pd.DataFrame()).to_dict() == previous.to_dict()


def test_failed_calculation_is_atomic(monkeypatch):
    import easy_tdx.chanlun.analyser as module

    analyser = ChanlunAnalyser()
    previous = analyser.process_klines(frame())
    calculate = module.calc_macd
    def broken(*args):
        raise RuntimeError('test failure')
    monkeypatch.setattr(module, 'calc_macd', broken)
    with pytest.raises(RuntimeError, match='test failure'):
        analyser.process_klines(frame(10))
    assert analyser.result is previous
    monkeypatch.setattr(module, 'calc_macd', calculate)
    assert analyser.append_klines(pd.DataFrame()).to_dict() == previous.to_dict()


def test_date_alias_and_string_prices_are_normalised_without_mutating_input():
    original = frame(5).rename(columns={'datetime': 'date'}).astype(str).drop(columns='vol')
    unchanged = original.copy(deep=True)
    result = ChanlunAnalyser().process_klines(original)
    assert result.klines[0].date == pd.Timestamp('2026-01-01')
    assert result.klines[0].amount == 0
    assert result.to_dict()['kline_count'] == 5
    pd.testing.assert_frame_equal(original, unchanged)


def test_bad_append_preserves_snapshot_and_allows_a_later_valid_update():
    analyser = ChanlunAnalyser()
    previous = analyser.process_klines(frame())
    update = frame().iloc[[10]].copy()
    update.loc[10, 'vol'] = -1
    with pytest.raises(ValueError):
        analyser.append_klines(update)
    assert analyser.result is previous
    update.loc[10, 'vol'] = 999
    result = analyser.append_klines(update)
    assert result.klines[10].amount == 999
    assert previous.klines[10].amount == 100


def test_missing_all_columns_is_rejected_not_silently_treated_as_empty():
    with pytest.raises(ValueError, match='缺少必要列'):
        ChanlunAnalyser().process_klines(pd.DataFrame(index=range(3)))


def test_confirmed_raw_pipeline_prefixes_never_gain_future_endpoints():
    from random import Random

    def signature(lines):
        return [(line.start.val, line.end.val, line.start.k.index, line.end.k.index,
                 line.confirmed_index) for line in lines if line.confirmed_index is not None]

    for seed in range(10):
        rng = Random(seed)
        prices, price = [], 100
        for _ in range(140):
            price += rng.uniform(-5, 5)
            prices.append(price)
        data = pd.DataFrame({'datetime': pd.date_range('2026-01-01', periods=140),
                             'open': prices, 'close': prices,
                             'high': [p + rng.uniform(0, 3) for p in prices],
                             'low': [p - rng.uniform(0, 3) for p in prices], 'vol': 100})
        full = ChanlunAnalyser().process_klines(data)
        for count in range(20, 140, 11):
            observed = ChanlunAnalyser().process_klines(data.iloc[:count])
            for field in ('bis', 'xds'):
                expected = [line for line in getattr(full, field)
                            if line.confirmed_index is not None and line.confirmed_index < count]
                assert signature(getattr(observed, field)) == signature(expected), (seed, count, field)


@pytest.mark.asyncio
async def test_invalid_vendor_bars_produce_explicit_stock_error(monkeypatch):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    import easy_tdx.web.routers.chanlun as route
    from easy_tdx.web.schemas import ChanlunRequest

    monkeypatch.setattr(route, 'fetch_adjusted_bars', AsyncMock(return_value=frame().iloc[::-1]))
    with pytest.raises(HTTPException) as exc:
        await route.chanlun_analyze(ChanlunRequest(market='SZ', code='000001'), None, None)
    assert exc.value.status_code == 502
    assert '股票行情数据异常' in exc.value.detail and '严格递增' in exc.value.detail


@pytest.mark.asyncio
async def test_invalid_vendor_bars_produce_explicit_industry_error(monkeypatch):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException
    import easy_tdx.web.routers.chanlun as route

    monkeypatch.setattr(route, 'stock_industries', AsyncMock(return_value=[
        {'board_code': '881155', 'market': 90}]))
    client = AsyncMock()
    client.get_stock_kline.return_value = frame().iloc[::-1]
    with pytest.raises(HTTPException) as exc:
        await route.industry_analyze(route.IndustryRequest(
            stock_market='SZ', stock_code='000001', board_code='881155'), client)
    assert exc.value.status_code == 502
    assert '行业行情数据异常' in exc.value.detail and '严格递增' in exc.value.detail
