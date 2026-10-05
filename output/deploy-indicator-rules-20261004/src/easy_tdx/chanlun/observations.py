"""Explainable MA/volume/MACD context. Never produces formal buy/sell points."""
import pandas as pd

from easy_tdx.chanlun import ChanlunAnalyser


def observe(frame: pd.DataFrame, category: str, *, volume_multiple: float = 2.0,
            squeeze_quantile: float = .2) -> dict:
    close, vol = frame.close, frame.vol
    ma5, ma10 = close.rolling(5).mean(), close.rolling(10).mean()
    v5, v10 = vol.rolling(5).mean(), vol.rolling(10).mean()
    result = ChanlunAnalyser(frequency=category).process_klines(frame)
    macd = result.macd

    def number(value):
        return float(value) if pd.notna(value) else None

    def pair(fast, slow):
        if len(fast) < 2 or pd.isna(fast.iloc[-2]) or pd.isna(slow.iloc[-2]):
            return {'state': '样本不足', 'fast': number(fast.iloc[-1]), 'slow': number(slow.iloc[-1])}
        gap, prev = fast.iloc[-1] - slow.iloc[-1], fast.iloc[-2] - slow.iloc[-2]
        state = ('刚上穿' if gap > 0 >= prev else '刚下穿' if gap < 0 <= prev else
                 '快线上方' if gap > 0 else '快线下方' if gap < 0 else '双线相等')
        return {'state': state, 'fast': float(fast.iloc[-1]), 'slow': float(slow.iloc[-1]),
                'gap_change': float(gap - prev), 'fast_slope': float(fast.iloc[-1] - fast.iloc[-2]),
                'slow_slope': float(slow.iloc[-1] - slow.iloc[-2])}

    dif, dea, hist = (pd.Series(macd[k]) for k in ('dif', 'dea', 'hist'))
    pairs = {'ma': pair(ma5, ma10), 'volume': pair(v5, v10), 'macd': pair(dif, dea)}
    d, e, h = dif.iloc[-1], dea.iloc[-1], hist.iloc[-1]
    axis = '零轴上方' if d > 0 and e > 0 else '零轴下方' if d < 0 and e < 0 else '跨轴 / 触轴'
    histogram = ('红柱' if h > 0 else '绿柱' if h < 0 else '零柱')
    if len(hist) > 1:
        histogram += (' · 换色' if h * hist.iloc[-2] < 0 else
                      ' · 缩短' if abs(h) < abs(hist.iloc[-2]) else ' · 延长' if abs(h) > abs(hist.iloc[-2]) else ' · 持平')
    observations = []
    if all('gap_change' in pair_ and pair_['gap_change'] > 0 for pair_ in pairs.values()):
        observations.append('三组快慢线差值同时增加；仅表示联合修复，不等于买点')
    elif all('gap_change' in pair_ and pair_['gap_change'] < 0 for pair_ in pairs.values()):
        observations.append('三组快慢线差值同时减少；联合动能减弱')
    mean = close.rolling(20).mean()
    width = 4 * close.rolling(20).std(ddof=0) / mean.abs().replace(0, float('nan'))
    if len(frame) >= 40:
        reference = width.iloc[-121:-1].dropna()
        if len(reference) >= 20 and width.iloc[-1] <= reference.quantile(squeeze_quantile):
            observations.append(f'BOLL 带宽处于此前最多 120 根的低 {squeeze_quantile * 100:g}% 区间')
        if width.iloc[-1] > width.iloc[-2]:
            observations.append('BOLL 带宽扩张（不表示突破方向）')
    previous_vol = vol.iloc[-21:-1].mean() if len(frame) >= 21 else float('nan')
    ratio = vol.iloc[-1] / previous_vol if previous_vol > 0 else float('nan')
    if len(frame) >= 21:
        if ratio >= volume_multiple:
            observations.append(f'成交量为前 20 根均量的 {ratio:.2f} 倍，达到异常放量观察阈值')
        if close.iloc[-1] < close.iloc[-2] and ratio < 1:
            observations.append('缩量回调：本根收盘下跌，量低于前 20 根均量')
        if close.iloc[-1] > frame.high.iloc[-21:-1].max() and ratio >= volume_multiple:
            observations.append('放量突破前 20 根最高价；尚非结构三买')
        if frame.low.iloc[-1] < frame.low.iloc[-21:-1].min() and h >= 0:
            observations.append('价格创前 20 根新低，但未形成负向 MACD 柱；特殊观察，非一买')
    active = [b for b in result.bcs if b.status != 'superseded']
    latest = sorted(active, key=lambda b: b.detected_index or 0)[-3:]
    return {
        'category': category, 'bar_count': len(frame), 'last_date': str(frame.datetime.iloc[-1]),
        'price': float(close.iloc[-1]), 'ma5': number(ma5.iloc[-1]), 'ma10': number(ma10.iloc[-1]),
        'above_ma5': bool(close.iloc[-1] >= ma5.iloc[-1]) if pd.notna(ma5.iloc[-1]) else None,
        'above_ma10': bool(close.iloc[-1] >= ma10.iloc[-1]) if pd.notna(ma10.iloc[-1]) else None,
        'pairs': pairs, 'axis': axis, 'histogram': histogram,
        'dif_toward_zero': bool(abs(d) < abs(dif.iloc[-2])) if len(dif) > 1 else None,
        'dea_toward_zero': bool(abs(e) < abs(dea.iloc[-2])) if len(dea) > 1 else None,
        'boll_width': number(width.iloc[-1]), 'volume_ratio': number(ratio),
        'observations': observations,
        'divergences': [{'kind': b.bc_type.value, 'direction': b.direction, 'status': b.status,
                         'date': str(frame.datetime.iloc[b.signal_index]),
                         'confirmed_date': str(frame.datetime.iloc[b.confirmed_index]) if b.confirmed_index is not None else None}
                        for b in latest if b.signal_index is not None],
        'structure': {'confirmed_pens': sum(p.confirmed_index is not None for p in result.bis),
                      'segments': len(result.xds), 'centres': len(result.structural_centres),
                      'state': result.structural_centres[-1].state if result.structural_centres else 'none'},
        'warmup_warning': len(frame) < 120, 'eligible_for_trading': False,
    }
