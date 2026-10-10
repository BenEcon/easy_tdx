"""Causal descriptive context, isolated from strict structures and trading signals."""
from __future__ import annotations

import math
import pandas as pd

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.bi import _can_form_bi, _first_observable, find_bis
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines

DEFAULT_MA = (5, 10, 20, 30, 60, 120, 250)
RULE_VERSION = 'multi-period-observation-20261009'


def number(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def stamp(frame, index):
    return str(frame.datetime.iloc[index])


def sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def direction(value):
    return '样本不足' if value is None else '上升' if value > 0 else '下降' if value < 0 else '持平'


def pair_context(fast, slow, kind):
    f, s = number(fast.iloc[-1]), number(slow.iloc[-1])
    prev_f = number(fast.iloc[-2]) if len(fast) > 1 else None
    prev_s = number(slow.iloc[-2]) if len(slow) > 1 else None
    names = {'ma': ('MA5', 'MA10'), 'volume': ('MAVOL5', 'MAVOL10'), 'macd': ('DIF', 'DEA')}[kind]
    out = {'fast': f, 'slow': s, 'state': '样本不足', 'description': '样本不足',
           'gap': None, 'relative_gap': None, 'fast_slope': None, 'slow_slope': None,
           'gap_change': None, 'directions': '样本不足', 'position_bars': 0}
    if f is None or s is None:
        return out
    gap = f - s
    out.update(gap=gap, relative_gap=gap / abs(s) * 100 if s != 0 and kind != 'macd' else None)
    state = '快线上方' if gap > 0 else '快线下方' if gap < 0 else '双线相等'
    n = 0
    for a, b in reversed(list(zip(fast, slow))):
        if pd.isna(a) or pd.isna(b) or sign(a - b) != sign(gap):
            break
        n += 1
    out.update(state=state, position_bars=n)
    if prev_f is None or prev_s is None:
        out['description'] = f'{names[0]} 在 {names[1]} ' + ('上方' if gap > 0 else '下方' if gap < 0 else '重合；尚无前根比较')
        return out
    prev = prev_f - prev_s
    fs, ss = f - prev_f, s - prev_s
    out.update(fast_slope=fs, slow_slope=ss, gap_change=gap-prev,
               directions=f'{names[0]} {direction(fs)}；{names[1]} {direction(ss)}')
    crossing = '刚上穿' if gap > 0 >= prev else '刚下穿' if gap < 0 <= prev else None
    if crossing:
        out.update(state=crossing, description=f'{names[0]} {crossing} {names[1]}')
    elif gap == 0:
        out['description'] = '双线相等，不算严格排列'
    else:
        shrinking = abs(gap) < abs(prev)
        widening = abs(gap) > abs(prev)
        position = '上方' if gap > 0 else '下方'
        change = '收窄' if shrinking else '扩大' if widening else '持平'
        out['description'] = f'{names[0]} 位于 {names[1]} {position}，间距{change}'
        if kind == 'ma':
            if gap > 0 and fs > 0 and ss > 0 and widening:
                out['description'] = '短期多头展开，双线共同上升'
            elif gap < 0 and fs < 0 and ss < 0 and widening:
                out['description'] = '短期空头展开，双线共同下降'
            elif gap < 0 and shrinking:
                out['description'] = '短期均线由下方趋近，修复中'
            elif gap > 0 and shrinking:
                out['description'] = '短期多头收敛'
        elif kind == 'volume':
            out['description'] = ('短期均量优势' if gap > 0 else '短期均量相对差距') + change
    return out


def arrangement(values, periods, i, side):
    """Stop at the FIRST missing/equal/reversed relation; never skip an MA."""
    reached = None
    if pd.isna(values[periods[0]].iloc[i]):
        return {'to': None, 'reason': f'MA{periods[0]} 样本不足', 'complete': False}
    for a, b in zip(periods, periods[1:]):
        fa, fb = values[a].iloc[i], values[b].iloc[i]
        if pd.isna(fb):
            reason = f'MA{b} 样本不足'
            break
        if fa == fb:
            reason = f'MA{a} 与 MA{b} 相等'
            break
        if (fa-fb)*side <= 0:
            reason = f'尚未满足 MA{a} {">" if side == 1 else "<"} MA{b}'
            break
        reached = b
    else:
        return {'to': reached, 'reason': '全部已验证' if len(periods) > 1 else '仅一条均线，不判断排列',
                'complete': len(periods) > 1}
    return {'to': reached, 'reason': reason, 'complete': False}


def indicator_events(frame, pairs, values, periods, start):
    """Every event has an exact first observed time and first invalidation time."""
    events = []
    tracks = {}
    dif, dea = pairs['macd']
    hist = 2*(dif-dea)

    def record(i, key, positive, negative, state, previous):
        if state == previous:
            return
        if key in tracks:
            tracks[key]['active'] = False
            tracks[key]['invalidated_at'] = stamp(frame, i)
        if state == 0:
            tracks.pop(key, None)
            return
        event = {'index': i, 'date': stamp(frame, i), 'key': key, 'direction': state,
                 'label': positive if state > 0 else negative, 'active': True,
                 'invalidated_at': None, 'bars_ago': len(frame)-1-i}
        events.append(event)
        tracks[key] = event

    for i in range(1, len(frame)):
        for key, (f, s) in pairs.items():
            if pd.isna(f.iloc[i-1]) or pd.isna(s.iloc[i-1]):
                continue
            names = {'ma': 'MA5 / MA10', 'volume': 'MAVOL5 / MAVOL10', 'macd': 'DIF / DEA'}[key]
            record(i, key, f'{names} 上穿', f'{names} 下穿', sign(f.iloc[i]-s.iloc[i]), sign(f.iloc[i-1]-s.iloc[i-1]))
            record(i, f'{key}_repair', f'{names} 差值开始改善', f'{names} 差值改善中断',
                   sign((f.iloc[i]-s.iloc[i])-(f.iloc[i-1]-s.iloc[i-1])),
                   sign((f.iloc[i-1]-s.iloc[i-1])-(f.iloc[i-2]-s.iloc[i-2])) if i > 1 and pd.notna(s.iloc[i-2]) else 0)
        if sign(hist.iloc[i]) == sign(hist.iloc[i-1]) and abs(hist.iloc[i]) < abs(hist.iloc[i-1]):
            previous_shrink = i > 1 and sign(hist.iloc[i-1]) == sign(hist.iloc[i-2]) and abs(hist.iloc[i-1]) < abs(hist.iloc[i-2])
            record(i, 'hist_shrink', '绿柱开始缩短' if hist.iloc[i] < 0 else '红柱开始缩短', '', 1, 1 if previous_shrink else 0)
        elif 'hist_shrink' in tracks:
            tracks.pop('hist_shrink').update(active=False, invalidated_at=stamp(frame, i))
        for name, series in [('DIF', dif), ('DEA', dea)]:
            record(i, name, f'{name} 上穿零轴', f'{name} 下穿零轴', sign(series.iloc[i]), sign(series.iloc[i-1]))
        state = 1 if dif.iloc[i] > 0 and dea.iloc[i] > 0 else -1 if dif.iloc[i] < 0 and dea.iloc[i] < 0 else 0
        prev = 1 if dif.iloc[i-1] > 0 and dea.iloc[i-1] > 0 else -1 if dif.iloc[i-1] < 0 and dea.iloc[i-1] < 0 else 0
        record(i, 'both_axis', '双线共同位于零轴上方', '双线共同位于零轴下方', state, prev)
        for n in (5, 10):
            ma = values[n]
            if pd.notna(ma.iloc[i-1]):
                record(i, f'price_ma{n}', f'收盘价收回 MA{n}', f'收盘价跌回 MA{n} 下方',
                       sign(frame.close.iloc[i]-ma.iloc[i]), sign(frame.close.iloc[i-1]-ma.iloc[i-1]))
        for side in (1, -1):
            before, after = arrangement(values, periods, i-1, side), arrangement(values, periods, i, side)
            if before['to'] != after['to']:
                name = '多头' if side == 1 else '空头'
                key = f'arrangement_{side}'
                if key in tracks:
                    tracks[key].update(active=False, invalidated_at=stamp(frame, i))
                event = {'index': i, 'date': stamp(frame, i), 'key': key, 'direction': side,
                         'label': f'{name}排列' + (f'扩展至 MA{after["to"]}' if (after['to'] or 0) > (before['to'] or 0)
                                                 else f'收缩至 MA{after["to"]}' if after['to'] else '已破坏'),
                         'active': True, 'invalidated_at': None, 'bars_ago': len(frame)-1-i}
                events.append(event); tracks[key] = event
                if side == 1 and before['to'] and len(periods) >= 3 and before['to'] >= periods[2] and (after['to'] or 0) < periods[2]:
                    event['label'] += '（中期排列破坏）'
    return [e for e in events if e['index'] >= start]


def pen_direction(frame, bis, fractals):
    """Observe after the latest strict anchor; never write into bis/fractals."""
    names = {'up': '向上', 'down': '向下'}
    last = bis[-1] if bis else None
    anchor = last.end if last else (fractals[-1] if fractals else None)
    strict = None if last is None else {
        'direction': last.direction.value, 'start_date': stamp(frame, extreme_index(last.start)),
        'end_date': stamp(frame, extreme_index(last.end)), 'start_price': last.start.val,
        'end_price': last.end.val, 'locked': last.confirmed_index is not None,
        'confirmed_date': stamp(frame, last.confirmed_index) if last.confirmed_index is not None else None}
    out = {'strict': strict, 'state': 'insufficient', 'direction': None,
           'description': '尚无已成立分型，方向证据不足', 'anchor_date': None,
           'anchor_price': None, 'known_date': None, 'projection': None,
           'invalidation': '等待本级分型', 'confirmation': '等待严格价格、分型和独立 K 线间距同时满足'}
    if anchor is None:
        return out
    start = extreme_index(anchor)
    top = anchor.fx_type.value == 'ding'
    side = 'down' if top else 'up'
    tail = frame.iloc[start+1:]
    known = min(len(frame)-1, _first_observable(anchor))
    out.update(anchor_date=stamp(frame, start), anchor_price=anchor.val, known_date=stamp(frame, known),
               invalidation=f'观察{"高" if top else "低"}点 {anchor.val:g} 被{"突破" if top else "跌破"}即撤销本轮观察')
    if not tail.empty and (tail.high.max() > anchor.val if top else tail.low.min() < anchor.val):
        out.update(state='invalidated', direction='up' if top else 'down',
                   description='原反向观察已被新极值否定；原方向延伸，等待新分型')
        return out
    out.update(direction=side, state='waiting', description=f'{names[side]}观察，尚未严格成笔')
    if not tail.empty:
        field = 'low' if top else 'high'
        end = int(tail[field].idxmin() if top else tail[field].idxmax())
        end_price = float(frame[field].iloc[end])
        if (end_price < anchor.val if top else end_price > anchor.val):
            out['projection'] = {'start_date': stamp(frame, start), 'end_date': stamp(frame, end),
                                 'start_price': anchor.val, 'end_price': end_price, 'direction': side}
    reverse = [f for f in fractals if f.k.index > anchor.k.index and f.fx_type != anchor.fx_type]
    if reverse:
        candidate = reverse[-1]
        valid = _can_form_bi(anchor, candidate, ChanlunConfig())
        out.update(state='formed' if valid else 'fractal_waiting',
                   description=f'{names[side]}笔条件已满足，尾端仍可延伸' if valid else f'已有反向局部分型；{names[side]}待成笔，严格价格或间距尚未满足')
    if tail.empty:
        out['description'] = '分型已成立；等待端点之后的反向运动'
    return out


def direction_history(frame, raw, start):
    """Prefix reconstruction avoids dating a mutable endpoint with future data."""
    events, previous = [], None
    for i in range(max(2, start-1), len(frame)):
        fxs = find_fractals(merge_klines(raw[:i+1]))
        pens = find_bis(fxs)
        state = pen_direction(frame.iloc[:i+1], pens, fxs)
        key = (state['state'], state['direction'], state['anchor_date'],
               state['strict']['end_date'] if state['strict'] else None)
        if key != previous and i >= start:
            events.append({'date': stamp(frame, i), 'state': state['state'], 'description': state['description'],
                           'anchor_date': state['anchor_date'], 'known_date': state['known_date']})
        previous = key
    return events


def recent_context(frame, fractals, start):
    window = frame.iloc[start:]
    first, last = float(window.close.iloc[0]), float(window.close.iloc[-1])
    change = (last/first-1)*100 if first != 0 else None
    ranges = float(window.high.max()-window.low.min())
    net = last-first
    # Explicit engineering statistic, not a Chan trend definition.
    overall = '上行' if net > ranges*.2 else '下行' if net < -ranges*.2 else '横向波动'
    tops = [f for f in fractals if f.fx_type.value == 'ding' and extreme_index(f) >= start]
    bottoms = [f for f in fractals if f.fx_type.value == 'di' and extreme_index(f) >= start]
    evidence = '结构证据不足：窗口内须至少各有两个已成立顶底分型'
    if len(tops) >= 2 and len(bottoms) >= 2:
        t, b = sign(tops[-1].val-tops[-2].val), sign(bottoms[-1].val-bottoms[-2].val)
        evidence = ('高低点共同抬高' if t > 0 and b > 0 else '高低点共同降低' if t < 0 and b < 0
                    else '高低点范围扩张' if t > 0 and b < 0 else '高低点范围收缩' if t < 0 and b > 0 else '高低点等高等低或方向分歧')
    tail = '方向尚不明确'
    turn = next((f for f in reversed(fractals) if extreme_index(f) >= start), None)
    if turn:
        delta = last - turn.val
        tail = '末端回落' if delta < 0 else '末端反弹' if delta > 0 else '停留在观察极值'
    if len(window) > 2:
        prior_high, prior_low = float(window.high.iloc[:-1].max()), float(window.low.iloc[:-1].min())
        if last > prior_high:
            tail = '收盘突破窗口此前最高价'
        elif last < prior_low:
            tail = '收盘跌破窗口此前最低价'
        elif tops:
            last_top = tops[-1]
            following = frame.iloc[extreme_index(last_top)+1:]
            if len(following) > 1 and (following.close.iloc[:-1] > last_top.val).any() and last >= last_top.val and last < following.close.max():
                tail = '突破前高后回试，收盘暂未失守该前高'
        if bottoms and tail in ('末端反弹', '末端回落', '方向尚不明确'):
            last_bottom = bottoms[-1]
            following = frame.iloc[extreme_index(last_bottom)+1:]
            if len(following) > 1 and (following.close.iloc[:-1] < last_bottom.val).any() and last <= last_bottom.val and last > following.close.min():
                tail = '跌破前低后回抽，收盘暂未收回该前低'
    rolling_peak = window.close.cummax()
    drawdown = ((window.close/rolling_peak.replace(0, float('nan'))-1)*100).min()
    return {'overall': overall, 'tail': tail, 'structure': evidence, 'change_pct': change,
            'high': float(window.high.max()), 'low': float(window.low.min()),
            'max_close_drawdown_pct': number(drawdown), 'first_close': first, 'last_close': last,
            'summary': f'近期整体{overall}，{tail}；{evidence}',
            'method': '净收盘变化超过窗口高低范围的 20% 记为上行/下行，否则记为横向波动；不是缠论趋势认定'}


def build_context(frame, result, *, ma_periods=DEFAULT_MA, window_bars=20, window_start=None):
    frame = frame.reset_index(drop=True)
    start = max(0, len(frame)-window_bars)
    if window_start is not None:
        indices = frame.index[pd.to_datetime(frame.datetime) >= pd.Timestamp(window_start)]
        if not len(indices):
            return {'error': '指定研究区间内没有已收盘 K 线'}
        start = int(indices[0])
    periods = sorted(set(ma_periods))
    values = {p: frame.close.rolling(p).mean() for p in set(periods) | {5, 10}}
    volume = {p: frame.vol.rolling(p).mean() for p in (5, 10)}
    dif, dea, hist = [pd.Series(result.macd[k]) for k in ('dif', 'dea', 'hist')]
    sequences = {'ma': (values[5], values[10]), 'volume': (volume[5], volume[10]), 'macd': (dif, dea)}
    pairs = {name: pair_context(*pair, name) for name, pair in sequences.items()}
    events = indicator_events(frame, sequences, values, periods, start)
    links = []
    for key, name in [('ma', '价格均线'), ('volume', '均量'), ('macd', 'MACD')]:
        candidates = [e for e in events if e['key'] in (key, f'{key}_repair') and e['direction'] > 0 and e['active']]
        # A cross long ago cannot outweigh weakening now; and no event outside this window counts.
        current = pairs[key]
        sustained = (bool(candidates) and current['gap_change'] is not None and current['gap_change'] >= 0
                     and current['fast_slope'] is not None and current['fast_slope'] > 0)
        links.append({'key': key, 'label': name, 'supported': sustained,
                      'date': candidates[-1]['date'] if candidates else None,
                      'description': f'{name}改善仍在持续' if sustained else f'{name}改善中断或窗口内无有效修复事件'})
    summary = ('价格、均量与 MACD 在本窗口内先后改善，目前仍保持向上配合' if all(l['supported'] for l in links)
               else '；'.join(l['description'] for l in links))
    streak = 0
    for i in range(len(hist)-1, 0, -1):
        if sign(hist.iloc[i]) != sign(hist.iloc[i-1]) or abs(hist.iloc[i]) >= abs(hist.iloc[i-1]):
            break
        streak += 1
    axes = []
    for key in ('DIF', 'DEA', 'both_axis'):
        up = [e for e in events if e['key'] == key and e['direction'] > 0]
        axes.append({'key': key, 'first_up': up[0]['date'] if up else None,
                     'last_up': up[-1]['date'] if up else None,
                     'invalidated_at': up[-1]['invalidated_at'] if up else None,
                     'currently_above': bool(dif.iloc[-1] > 0 and dea.iloc[-1] > 0) if key == 'both_axis'
                     else bool((dif if key == 'DIF' else dea).iloc[-1] > 0)})
    observation = pen_direction(frame, result.bis, result.fractals)
    observation['history'] = direction_history(frame, result.klines, start)
    for key, n in [('ma5', 5), ('ma10', 10)]:
        count = 0
        for price, ma in reversed(list(zip(frame.close, values[n]))):
            if pd.isna(ma) or price <= ma:
                break
            count += 1
        pairs['ma'][f'above_{key}_bars'] = count
    ma_lines = [{'period': p, 'value': number(values[p].iloc[-1]),
                 'slope': number(values[p].iloc[-1]-values[p].iloc[-2]) if len(frame) > 1 else None}
                for p in periods]
    gaps = [{'fast': a, 'slow': b, 'gap': number(values[a].iloc[-1]-values[b].iloc[-1]),
             'gap_change': number((values[a].iloc[-1]-values[b].iloc[-1])-(values[a].iloc[-2]-values[b].iloc[-2])) if len(frame) > 1 else None}
            for a, b in zip(periods, periods[1:])]
    return {'window': {'start': stamp(frame, start), 'end': stamp(frame, len(frame)-1),
                       'count': len(frame)-start, 'requested_bars': window_bars if window_start is None else None,
                       'truncated': len(frame) < window_bars if window_start is None else pd.Timestamp(frame.datetime.iloc[0]) > pd.Timestamp(window_start),
                       'warmup_bars': start},
            'ma_research': {'periods': periods, 'bull': arrangement(values, periods, len(frame)-1, 1),
                            'bear': arrangement(values, periods, len(frame)-1, -1), 'lines': ma_lines, 'gaps': gaps},
            'pairs': pairs, 'recent': recent_context(frame, result.fractals, start),
            'events': events, 'coordination': {'summary': summary, 'components': links},
            'axis_history': axes, 'histogram_shrinking_bars': streak, 'direction_observation': observation}
