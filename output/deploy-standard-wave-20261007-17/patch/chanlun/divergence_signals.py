"""Causal MACD divergence events and conservative, structure-gated trend signals.

Events are evaluated on prefixes: a later bar never creates an earlier confirmation.
An indicator observation waits for a first-formed reverse pen from its exact extreme.
A lower/higher extreme or broken MACD comparison invalidates a pending candidate.
Trend signals additionally require two disjoint same-level pen centres and completed
entry/exit legs; they deliberately do not promote ordinary MACD divergence to 1buy.
"""
from __future__ import annotations

from copy import deepcopy
from math import isfinite

from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.bi import find_bis, _can_form_bi
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.types import BC, MMD, BCType, Kline, MMDType
from easy_tdx.chanlun.zs import find_zss

INDICATOR_RULE_VERSION = 2026100414
STANDARD_WAVE_RULE_VERSION = 2026100717


def _pivot_candidates(bars: list[Kline], macd: dict[str, list[float]],
                      diagnostics: list[dict] | None = None) -> list[BC]:
    """Causal nearest-pivot detection, independent of subsequent completion.

    A top requires a strictly higher high and BOTH DIF/DEA lower at that high
    than at the reference high, with all four values above zero. A bottom uses
    the inverse inequalities below zero. Histogram colour is not a prerequisite
    for this two-pivot indicator signal (unlike the separate wave comparison).
    """
    events: list[BC] = []
    # Independently track low and high swings, always using an intervening rebound.
    for direction, sign, key in (("down", 1, "low"), ("up", -1, "high")):
        reference: int | None = None
        pivot: int | None = None
        for i in range(1, len(bars)):
            if not bars[i].is_closed:
                break
            more_extreme = sign * getattr(bars[i], key) < sign * getattr(bars[i - 1], key)
            if pivot is None and more_extreme:
                pivot = i
            elif pivot is not None and sign * getattr(bars[i], key) < sign * getattr(bars[pivot], key):
                pivot = i
            if pivot is None:
                continue
            if i == pivot and reference is None and diagnostics is not None:
                diagnostics.append({'family': 'double', 'direction': direction,
                    'c_start': i, 'c_end': i, 'known_index': i, 'first_checked_index': i,
                    'first_candidate_index': None, 'status': 'blocked', 'closed': False,
                    'checks': [{'gate': 'dual_reference_available', 'passed': False, 'values': {}}],
                    'comparisons': [], 'rejections': [{'from_index': i, 'through_index': i,
                                                       'gates': ['dual_reference_available']}]})
            if i == pivot and reference is not None:
                p = reference
                price_break = sign * getattr(bars[i], key) < sign * getattr(bars[p], key) - 1e-6
                lines_improve = all(
                    sign * macd[line][i] > sign * macd[line][p] + 1e-9
                    and sign * macd[line][i] < 0 and sign * macd[line][p] < 0
                    for line in ("dif", "dea")
                )
                if diagnostics is not None:
                    checks = [{'gate': 'dual_price_break', 'passed': price_break,
                               'values': {'a_price': getattr(bars[p], key), 'c_price': getattr(bars[i], key)}}]
                    checks.extend({'gate': f'dual_{line}_improves', 'passed':
                                   sign * macd[line][i] > sign * macd[line][p] + 1e-9
                                   and sign * macd[line][i] < 0 and sign * macd[line][p] < 0,
                                   'values': {'previous_index': p, 'current_index': i,
                                              'previous_value': macd[line][p], 'current_value': macd[line][i]}}
                                  for line in ('dif', 'dea'))
                    diagnostics.append({'family': 'double', 'direction': direction,
                        'a_start': p, 'a_end': p, 'c_start': i, 'c_end': i, 'known_index': i,
                        'first_checked_index': i, 'first_candidate_index': i if price_break and lines_improve else None,
                        'status': 'candidate' if price_break and lines_improve else 'blocked',
                        'closed': False, 'checks': checks, 'comparisons': [],
                        'rejections': [] if price_break and lines_improve else [{'from_index': i,
                            'through_index': i, 'gates': [c['gate'] for c in checks if not c['passed']]}]})
                if price_break and lines_improve:
                    candidate = BC(
                        bc_type=BCType.MACD, bc=True, signal_index=i,
                        reference_index=p, detected_index=i, status="candidate",
                        direction=direction,
                        msg=("MACD 双线底背离：价格严格低于最近局部低点，该低点对应的 DIF、DEA 均抬高，且均在零轴下方；非缠论一买。"
                             if direction == "down" else
                             "MACD 双线顶背离：价格严格高于最近局部高点，该高点对应的 DIF、DEA 均回落，且均在零轴上方；非缠论一卖。"),
                        evidence={"rule_version": INDICATOR_RULE_VERSION,
                                  "price": getattr(bars[i], key), "previous_price": getattr(bars[p], key),
                                  "dif": macd["dif"][i], "previous_dif": macd["dif"][p],
                                  "dea": macd["dea"][i], "previous_dea": macd["dea"][p]},
                    )
                    # Presentation subtype only: keep the nearest-pivot evidence
                    # and the same reverse-pen lifecycle. Opposite-colour bars at
                    # the signal extreme are NOT a zero-area C wave or an M1.
                    # Freeze the colour at detection; later colour changes must
                    # not rewrite the historical marker family.
                    hist = macd.get("hist", [])
                    if len(hist) > i and isfinite(hist[i]) and sign * hist[i] > 0:
                        candidate.evidence.update(special_no_c=1, signal_hist=hist[i])
                    events.append(candidate)
            if i > pivot and sign * getattr(bars[i], key) > sign * getattr(bars[pivot], key):
                # Every completed local swing replaces the reference, even if
                # it is a higher low / lower high. Never skip it for an older,
                # more favourable price or MACD comparison; no pen is required.
                reference = pivot
                pivot = None
    return sorted(events, key=lambda e: (e.detected_index or 0, e.direction))


def indicator_events(bars: list[Kline], macd: dict[str, list[float]],
                     config: ChanlunConfig | None = None, *, diagnostics: list[dict] | None = None) -> list[BC]:
    """Separate early MACD evidence from final reverse-pen confirmation.

    An exact reverse pen first formed on the current prefix is sufficient for
    this indicator observation. Structural pen locking remains unchanged.
    Confirmed historical events are frozen, not retrospectively erased by a new leg.
    """
    reports: list[dict] = []
    events = _pivot_candidates(bars, macd, reports if diagnostics is not None else None)
    _confirm_reverse_pen_events(events, bars, macd, config)
    if diagnostics is not None:
        for report in reports:
            event = next((e for e in events if e.signal_index == report['c_start']
                          and e.direction == report['direction']), None)
            if event is not None:
                report['status'] = 'blocked' if event.status == 'superseded' else event.status
                report['known_index'] = event.confirmed_index or event.invalidated_index or len(bars)-1
                if event.failure_audit:
                    report['checks'].extend(deepcopy(event.failure_audit['checks']))
                    report['rejections'].append({'from_index': event.invalidated_index,
                        'through_index': event.invalidated_index,
                        'gates': [g['gate'] for g in event.failure_audit['checks'] if not g['passed']]})
                elif event.status == 'candidate':
                    report['checks'].append({'gate': 'reverse_pen_formed', 'passed': False,
                        'values': {'current_index': len(bars)-1}})
            diagnostics.append(report)
    return events


def _confirm_reverse_pen_events(events: list[BC], bars: list[Kline],
                                macd: dict[str, list[float]],
                                config: ChanlunConfig | None = None) -> list[BC]:
    """Shared causal lifecycle; each event retains its own reference evidence."""
    arrivals: dict[int, list[BC]] = {}
    for event in events:
        arrivals.setdefault(event.signal_index, []).append(event)
    pending: list[BC] = []
    config = config or ChanlunConfig()
    for now in range(len(bars)):
        if not bars[now].is_closed:
            break
        pending.extend(arrivals.get(now, []))
        for event in pending:
            sign = 1 if event.direction == 'down' else -1
            key = 'low' if sign == 1 else 'high'
            at = event.signal_index
            if now <= at:
                continue
            price_failed = sign * getattr(bars[now], key) < sign * event.evidence['price'] - 1e-6
            lines_failed = any(not isfinite(macd[line][now]) or
                               sign * macd[line][now] <= sign * event.evidence[f'previous_{line}'] + 1e-9
                               for line in ('dif', 'dea'))
            if price_failed or lines_failed:
                event.status = 'superseded'
                event.invalidated_index = now
                event.failure_reason = ('价格极值被后续新极值替代' if price_failed
                                        else '后续 DIF 或 DEA 不再优于对照极值')
                event.failure_audit = {'known_index': now, 'closed': False, 'checks': [
                    {'gate': 'candidate_price_retained', 'passed': not price_failed,
                     'values': {'previous_price': event.evidence['price'], 'price': getattr(bars[now], key)}},
                    *[{'gate': f'candidate_{line}_retained',
                       'passed': isfinite(macd[line][now]) and sign * macd[line][now] > sign * event.evidence[f'previous_{line}'] + 1e-9,
                       'values': {'a_extreme': event.evidence[f'previous_{line}'], 'c_extreme': macd[line][now]}}
                      for line in ('dif', 'dea')]]}
                continue
            hist = macd['hist']
            shrinking = (now >= at + 2 and all(sign * h <= 0 for h in hist[now-2:now+1])
                         and abs(hist[now]) < abs(hist[now-1]) < abs(hist[now-2]))
            changed = sign * hist[now-1] <= 0 < sign * hist[now]
            if event.preliminary_index is None and (shrinking or changed):
                event.preliminary_index = now
        pending = [event for event in pending if event.status == 'candidate']
        if not pending:
            continue
        fractals = find_fractals(merge_klines(bars[:now+1]), config)
        for event in pending:
            reverse = 'up' if event.direction == 'down' else 'down'
            # Indicator-only proof on the FULL known prefix. Do not slice and
            # re-merge at the anchor or require selection by the global pen chain.
            start = next((fx for fx in fractals if extreme_index(fx) == event.signal_index
                          and fx.fx_type.value == ('di' if reverse == 'up' else 'ding')), None)
            ends = [fx for fx in fractals if start is not None and fx.fx_type != start.fx_type
                    and fx.k.index > start.k.index]
            end = next((fx for fx in ends if _can_form_bi(start, fx, config)), None)
            event.evidence.update(rule_version=INDICATOR_RULE_VERSION,
                                  reverse_pen_local=1,
                                  reverse_pen_checked_index=now,
                                  reverse_pen_waiting=int(end is None))
            if end is None:
                code = 1 if start is None else 2
                if start is not None and ends:
                    observed = ends[-1]
                    top, bottom = (observed, start) if reverse == 'up' else (start, observed)
                    gap = observed.klines[0].index-start.klines[2].index-1
                    required = 1 if config.bi_type == 'new' else 3 if config.bi_type == 'old' else -999
                    code = (3 if top.k.high <= bottom.k.high or top.k.low <= bottom.k.low
                            else 4 if gap < required else 5)
                    event.evidence.update(reverse_pen_observed_gap=gap, reverse_pen_required_gap=required)
                event.evidence['reverse_pen_wait_code'] = code
            if end is not None:
                event.evidence.pop('reverse_pen_wait_code', None)
                event.evidence.pop('reverse_pen_observed_gap', None)
                event.evidence.pop('reverse_pen_required_gap', None)
                event.status = 'confirmed'
                event.confirmed_index = now
                event.evidence.update(reverse_pen_start=extreme_index(start),
                                      reverse_pen_end=extreme_index(end),
                                      reverse_pen_confirmed=now, reverse_pen_formed_index=now,
                                      reverse_pen_first_formed=1,
                                      reverse_pen_gap=end.klines[0].index-start.klines[2].index-1,
                                      reverse_pen_start_price=start.val,
                                      reverse_pen_end_price=end.val)
        pending = [event for event in pending if event.status == 'candidate']
    _link_replacements(events)
    return events


def _link_replacements(events: list[BC]) -> None:
    """Link only a real same-family candidate discovered at price invalidation.

    A new market extreme alone is not a replacement signal. No future search,
    cross-family association or mutation of confirmed historical proof.
    """
    for old in events:
        if old.status != 'superseded' or old.invalidated_index is None or '极值' not in old.failure_reason:
            continue
        replacement = next((new for new in events if new is not old
                            and new.bc_type == old.bc_type and new.direction == old.direction
                            and new.detected_index == old.invalidated_index
                            and new.signal_index != old.signal_index
                            and new.evidence.get('c_start') == old.evidence.get('c_start')
                            and new.evidence.get('b_start') == old.evidence.get('b_start')), None)
        if replacement is not None:
            old.evidence['replacement_signal_index'] = replacement.signal_index
            old.evidence['replacement_detected_index'] = replacement.detected_index


def special_wave_events(bars: list[Kline], macd: dict[str, list[float]],
                        config: ChanlunConfig | None = None,
                        *, diagnostics: list[dict] | None = None) -> list[BC]:
    """Price breaks A inside opposite-colour B, without inventing a C area.

    Price compares with the preceding A colour run's price extreme, while
    each B price-day indicator compares with its OWN full-A segment extreme.
    The two A indicator extrema need not occur on the same bar as each other
    or the A price extreme. Local-pivot MACD events keep their original basis.
    This is an independent AB observation; confirmation uses the same exact
    reverse-pen witness as dual-line observations, never colour change alone.
    """
    runs: list[list[int]] = []
    events: list[BC] = []
    reports: dict[int, dict] = {}
    for now, hist in enumerate(macd['hist']):
        if not bars[now].is_closed:
            break
        if not isfinite(hist):
            # Do not bridge a missing colour interval.
            runs = []
            continue
        colour = 1 if hist > 0 else -1 if hist < 0 else (runs[-1][0] if runs else 0)
        if not colour:
            continue
        if not runs or colour != runs[-1][0]:
            runs.append([colour, now, now])
        else:
            runs[-1][2] = now
        if len(runs) < 3:  # A must not be the left-truncated first run.
            if len(runs) == 2:
                a, b = runs
                reports[b[1]] = {'family': 'special', 'direction': 'down' if colour == 1 else 'up',
                    'a_start': a[1], 'a_end': a[2], 'b_start': b[1], 'b_end': now,
                    'known_index': now, 'first_checked_index': b[1], 'first_candidate_index': None,
                    'closed': False, 'status': 'blocked',
                    'checks': [{'gate': 'special_complete_a', 'passed': False, 'values': {}}],
                    'rejections': [{'from_index': b[1], 'through_index': now, 'gates': ['special_complete_a']}]}
            continue
        a, b = runs[-2:]
        sign = colour  # red B -> bottom; green B -> top
        direction, key = ('down', 'low') if sign == 1 else ('up', 'high')
        # A flat plateau is not a succession of new B price extremes.
        price_extreme = min(sign * getattr(bars[i], key) for i in range(b[1], now + 1))
        current = next(i for i in range(b[1], now + 1)
                       if sign * getattr(bars[i], key) <= price_extreme + 1e-6)
        if current != now or hist == 0:
            continue
        previous = min(range(a[1], a[2] + 1), key=lambda i: (sign * getattr(bars[i], key), -i))
        checks = []
        def gate(name, passed, **values):
            checks.append({'gate': name, 'passed': bool(passed), 'values': values})
        finite = all(len(macd.get(line, [])) > now and
                     all(isfinite(macd[line][i]) for i in range(a[1], now + 1))
                     for line in ('dif', 'dea', 'hist'))
        gate('special_ab_finite', finite)
        gate('special_b_price_break', sign * getattr(bars[now], key) <= sign * getattr(bars[previous], key) + 1e-6,
             a_price=getattr(bars[previous], key), b_price=getattr(bars[now], key),
             previous_index=previous, current_index=now, direction=direction)
        if finite:
            line_indices = {}
            for line in ('dif', 'dea'):
                line_index = min(range(a[1], a[2] + 1),
                                 key=lambda i: (sign * macd[line][i], -i))
                line_indices[line] = line_index
                before, after = macd[line][line_index], macd[line][now]
                gate(f'special_{line}_a_segment_extreme', sign * before < sign * after - 1e-9
                     and sign * before < 0 and sign * after < 0,
                     previous_value=before, current_value=after, previous_index=line_index,
                     current_index=now, direction=direction)
        passed = finite and all(g['passed'] for g in checks)
        report = reports.setdefault(b[1], {'family': 'special', 'direction': direction,
            'first_checked_index': now, 'first_candidate_index': None, 'rejections': []})
        report.update(a_start=a[1], a_end=a[2], b_start=b[1], b_end=now,
                      known_index=now, closed=False, status='candidate' if passed else 'blocked', checks=checks)
        if not passed:
            report['rejections'].append({'from_index': now, 'through_index': now,
                                         'gates': [g['gate'] for g in checks if not g['passed']]})
            continue
        if report['first_candidate_index'] is None:
            report['first_candidate_index'] = now
        events.append(BC(bc_type=BCType.MACD_WAVE_SPECIAL, bc=True, signal_index=now,
            reference_index=previous, detected_index=now, status='candidate', direction=direction,
            evidence={'a_start': a[1], 'a_end': a[2], 'b_start': b[1], 'b_end': now,
                      'price': getattr(bars[now], key), 'previous_price': getattr(bars[previous], key),
                      'dif': macd['dif'][now], 'previous_dif': macd['dif'][line_indices['dif']],
                      'dea': macd['dea'][now], 'previous_dea': macd['dea'][line_indices['dea']],
                      'a_dif_extreme_index': line_indices['dif'],
                      'a_dea_extreme_index': line_indices['dea'],
                      'special_a_segment_extrema': 1, 'rule_version': INDICATOR_RULE_VERSION,
                      'signal_hist': hist},
            msg=(f"MACD 特殊波段{'底' if sign == 1 else '顶'}背离："
                 + ("红柱 B 内价格达到或低于前一绿柱 A 最低点，双线抬高且同在零轴下；" if sign == 1 else
                    "绿柱 B 内价格达到或高于前一红柱 A 最高点，双线降低且同在零轴上；")
                 + "B 新价格极值当根双线分别比较 A 段内各自极值；无 C 面积，等待从极值起的反向笔确认，非结构一类点。")))
    _confirm_reverse_pen_events(events, bars, macd, config)
    if diagnostics is not None:
        for report in reports.values():
            matching = [e for e in events if e.evidence['b_start'] == report['b_start']]
            if matching and matching[-1].signal_index == report['known_index']:
                last = matching[-1]
                report['status'] = 'blocked' if last.status == 'superseded' else last.status
                if last.confirmed_index is not None:
                    report['known_index'] = last.confirmed_index
                if last.invalidated_index is not None:
                    report['known_index'] = last.invalidated_index
                    report['checks'].append({'gate': 'special_candidate_retained', 'passed': False,
                        'values': {'reason': last.failure_reason, 'failure_index': last.invalidated_index}})
                    report['rejections'].append({'from_index': last.invalidated_index,
                        'through_index': last.invalidated_index, 'gates': ['special_candidate_retained']})
                elif last.status == 'candidate':
                    report['known_index'] = last.evidence.get('reverse_pen_checked_index', last.signal_index)
                    report['checks'].append({'gate': 'reverse_pen_formed', 'passed': False,
                        'values': {'current_index': report['known_index']}})
            report['comparisons'] = []
        diagnostics.extend(reports.values())
    return events


def segment_evidence(bars: list[Kline], macd: dict[str, list[float]],
                     a: tuple[int, int], c: tuple[int, int], direction: str,
                     *, audit: list | None = None, whole_leg_axis: bool = False,
                     whole_abc_axis: bool = False, allow_equal_price: bool = False,
                     require_dea_improvement: bool = True,
                     whole_bc_axis: bool = False, exact_b_pullback: bool = False,
                     require_price_extreme: bool = True,
                     b_dif_excursion_limit: int | None = None) -> dict | None:
    """Compare complete, non-overlapping legs, not prices on selected dates.

    Whole-ABC exclusion stays strict unless the indicator-only B/DIF exception
    is explicitly requested. Structural compound legs retain their own rules.
    """
    a0, a1 = a
    c0, c1 = c
    def gate(name, passed, **values):
        if audit is not None:
            audit.append({'gate': name, 'passed': bool(passed), 'values': values})
        return passed
    if not gate('ordered_complete_intervals', 0 <= a0 <= a1 < c0 <= c1 < len(bars),
                a_start=a0, a_end=a1, c_start=c0, c_end=c1, bar_count=len(bars)):
        return None
    # Partial indicator windows must not look like smaller complete MACD areas.
    complete = True
    for key in ('dif', 'dea', 'hist'):
        values = macd.get(key, [])
        valid = len(values) > c1 and all(isfinite(value) for value in values[a0:c1 + 1])
        if not gate(f'{key}_finite_coverage', valid, length=len(values), required_end=c1):
            complete = False
            if audit is None:
                return None
    if not complete:
        return None
    down = direction == "down"
    sign = 1 if down else -1
    price_key = "low" if down else "high"
    pa = min(sign * getattr(k, price_key) for k in bars[a0:a1 + 1])
    pc = min(sign * getattr(k, price_key) for k in bars[c0:c1 + 1])
    area_a = sum(max(0, -sign * h) for h in macd["hist"][a0:a1 + 1])
    area_c = sum(max(0, -sign * h) for h in macd["hist"][c0:c1 + 1])
    price_ok = gate('c_price_unrestricted' if not require_price_extreme else
                    'equal_or_new_price_extreme' if allow_equal_price else 'strict_price_extreme',
                    True if not require_price_extreme else
                    pc <= pa + 1e-6 if allow_equal_price else pc < pa - 1e-6,
                    a_price=sign * pa, c_price=sign * pc, tolerance=1e-6)
    area_ok = gate('shrinking_same_colour_area', 0 < area_c < area_a,
                   a_area=area_a, c_area=area_c)
    passed = price_ok and area_ok
    if not passed and audit is None:
        return None
    evidence = {"a_start": a0, "a_end": a1, "c_start": c0, "c_end": c1,
                "a_area": area_a, "c_area": area_c,
                "area_ratio": area_c / area_a if area_a else None}
    for line in ('dif', 'dea'):
        if whole_bc_axis:
            violations = [i for i in range(a1 + 1, c1 + 1) if sign * macd[line][i] >= 0]
            axis_ok = gate(f'{line}_whole_bc_zero_axis', not violations,
                          violation_count=len(violations),
                          first_violation_index=violations[0] if violations else None,
                          first_violation_value=macd[line][violations[0]] if violations else None)
            passed = passed and axis_ok
        if whole_abc_axis:
            # Include B, never trim the crossing portion or silently reuse a
            # structural completion rule for this indicator-only observation.
            violations = [i for i in range(a0, c1 + 1) if sign * macd[line][i] >= 0
                          and not (line == 'dif' and b_dif_excursion_limit is not None and a1 < i < c0)]
            axis_ok = gate('dif_ac_zero_axis' if line == 'dif' and b_dif_excursion_limit is not None
                           else f'{line}_whole_abc_zero_axis', not violations,
                           a_start=a0, a_end=a1, c_start=c0, c_end=c1, direction=direction,
                           violation_count=len(violations),
                           first_violation_index=violations[0] if violations else None,
                           first_violation_value=macd[line][violations[0]] if violations else None)
            if not axis_ok and audit is None:
                return None
            passed = passed and axis_ok
        if line == 'dif' and b_dif_excursion_limit is not None:
            crossed = [i for i in range(a1 + 1, c0) if sign * macd[line][i] >= 0]
            episodes = sum(i == 0 or bar != crossed[i - 1] + 1 for i, bar in enumerate(crossed))
            excursion_ok = gate('b_dif_single_excursion', episodes <= 1 and len(crossed) <= b_dif_excursion_limit,
                                excursion_count=episodes, excursion_bars=len(crossed),
                                maximum_bars=b_dif_excursion_limit,
                                first_violation_index=crossed[0] if crossed else None,
                                last_violation_index=crossed[-1] if crossed else None)
            passed = passed and excursion_ok
            evidence.update(b_dif_excursion_count=episodes, b_dif_excursion_bars=len(crossed))
        if whole_leg_axis:
            same_side = all(sign * v < 0 for start, end in (a, c)
                            for v in macd[line][start:end + 1])
            axis_ok = gate(f'{line}_whole_leg_zero_axis', same_side,
                           a_start=a0, a_end=a1, c_start=c0, c_end=c1, direction=direction)
            if not axis_ok and audit is None:
                return None
            passed = passed and axis_ok
        av = min(sign * v for v in macd[line][a0:a1 + 1])
        cv = min(sign * v for v in macd[line][c0:c1 + 1])
        # Bottom: troughs rise below zero. Top: peaks fall above zero.
        values = dict(a_extreme=sign * av, c_extreme=sign * cv, direction=direction,
                      a_extreme_index=min(range(a0, a1 + 1), key=lambda i: sign * macd[line][i]),
                      c_extreme_index=min(range(c0, c1 + 1), key=lambda i: sign * macd[line][i]))
        if line == 'dea' and not require_dea_improvement:
            line_ok = gate('dea_zero_axis_without_improvement', av < 0 and cv < 0, **values)
        else:
            line_ok = gate(f'{line}_extreme_and_zero_axis', av < cv < 0, **values)
        if not line_ok and audit is None:
            return None
        # The intervening centre must have pulled both lines toward zero.
        pullback_values = macd[line][a1 + 1:c0] if exact_b_pullback else macd[line][a1:c0 + 1]
        pullback = max((sign * v for v in pullback_values), default=float('-inf'))
        pullback_ok = gate(f'{line}_centre_pullback', pullback > av,
                           a_extreme=sign * av, pullback=sign * pullback if pullback_values else None,
                           b_start_index=a1 + 1, b_end_index=c0 - 1)
        passed = passed and line_ok and pullback_ok
        if not pullback_ok and audit is None:
            return None
        evidence[f"a_{line}_extreme"] = sign * av
        evidence[f"c_{line}_extreme"] = sign * cv
        if exact_b_pullback:  # Indicator audit only; structural evidence stays unchanged.
            evidence[f"a_{line}_extreme_index"] = values['a_extreme_index']
            evidence[f"c_{line}_extreme_index"] = values['c_extreme_index']
    return evidence if passed else None


def _dea_tolerance_check(check: dict) -> dict:
    """Research-only 5% worsening cap; never relax axis, DIF, or area gates.

    Near-zero A (<= 1e-9) disables relative tolerance, not strict improvement.
    No absolute allowance or rounding epsilon is added to the 5% boundary.
    """
    values = deepcopy(check['values'])
    a, c = values['a_extreme'], values['c_extreme']
    sign = 1 if values['direction'] == 'down' else -1
    valid = isfinite(a) and isfinite(c)
    axis = valid and sign * a < 0 and sign * c < 0
    enabled = valid and abs(a) > 1e-9
    worsening = max(0.0, sign * (a - c)) if valid else None
    ratio = worsening / abs(a) if enabled else None
    strict = bool(check['passed'])
    passed = axis and (strict or (enabled and worsening <= .05 * abs(a)))
    values.update(tolerance_ratio=.05, relative_floor=1e-9, tolerance_enabled=enabled,
                  worsening_ratio=ratio, strict_passed=strict)
    return {'gate': 'dea_extreme_tolerance', 'passed': bool(passed), 'values': values}


def wave_rule_comparisons(bars: list[Kline], macd: dict[str, list[float]], record: dict) -> list[dict]:
    """Research-only final/prefix checks; never generate BC/MMD or alter defaults.

    Full A exempts only A from the whole-axis check, not B or C. All variants
    retain finite coverage, complete colour runs and strict area/DIF improvement.
    Only dea_tolerance relaxes DEA; it retains effective A and whole ABC axis.
    The 1e-6 price epsilon is numerical tolerance, not a tick band.
    """
    output = []
    for mode, full_a, equal in (('full_a', True, False), ('equal_price', False, True),
                                 ('full_a_equal_price', True, True), ('dea_tolerance', False, False)):
        checks = deepcopy([g for g in record['checks'] if g['gate'] in
                           ('complete_colour_abc', 'original_abc_finite')])
        a0 = record.get('original_a_start') if full_a else record.get('a_start')
        a1, c0, c1 = (record.get(k) for k in ('a_end', 'c_start', 'c_end'))
        if not full_a:
            checks.extend(deepcopy([g for g in record['checks'] if g['gate'] == 'a_axis_suffix']))
        evaluated = False
        if checks and all(g['passed'] for g in checks) and a0 is not None and a1 is not None:
            segment_evidence(bars, macd, (a0, a1), (c0, c1), record['direction'],
                             whole_abc_axis=not full_a, allow_equal_price=equal, audit=checks)
            evaluated = any(g['gate'] == 'dea_extreme_and_zero_axis' for g in checks)
            if mode == 'dea_tolerance':
                checks = [_dea_tolerance_check(g) if g['gate'] == 'dea_extreme_and_zero_axis' else g
                          for g in checks]
            if full_a:
                sign = 1 if record['direction'] == 'down' else -1
                for line in ('dif', 'dea'):
                    violations = [i for i in range(record['b_start'], c1 + 1) if sign * macd[line][i] >= 0]
                    checks.append({'gate': f'{line}_whole_bc_zero_axis', 'passed': not violations,
                                   'values': {'violation_count': len(violations),
                                              'first_violation_index': violations[0] if violations else None,
                                              'first_violation_value': macd[line][violations[0]] if violations else None}})
        output.append({'mode': mode, 'research_only': True, 'passed': evaluated and all(g['passed'] for g in checks),
                       'a_start': a0, 'a_end': a1, 'c_start': c0, 'c_end': c1,
                       'known_index': record['known_index'], 'closed': record['closed'], 'checks': checks})
    return output


def wave_events(bars: list[Kline], macd: dict[str, list[float]],
                *, diagnostics: list[dict] | None = None,
                family: str = 'standard', legacy_standard: bool = False) -> list[BC]:
    """Green/red/green (and mirrored) waves; confirm only on opposite colour.

    Exact zero bars extend the preceding wave; initial zero bars are ignored.
    The first observed wave is not a reference because its beginning may be cut off.
    A may be redefined as its terminal continuous same-axis suffix after BOTH
    lines enter the required side. Never trim B: the revised standard permits
    just one DIF excursion of at most five bars there; DEA remains same-side.
    Legacy standard retains the original whole-ABC exclusion. Prices,
    areas and line extrema all use the SAME effective A, not its excluded prefix.
    Local-pivot divergence is independent and is not a gate for these events.
    """
    if family not in ('standard', 'nonstandard'):
        raise ValueError('Unknown wave family')
    revised = family == 'standard' and not legacy_standard
    lines = ('dif', 'dea')
    wave_type = BCType.MACD_WAVE if family == 'standard' else BCType.MACD_WAVE_NONSTANDARD
    runs: list[list[int]] = []  # sign, start, end
    events: list[BC] = []
    active: BC | None = None
    reports: dict[int, dict] = {}

    def evaluate(now: int, ci: int, closed: bool) -> None:
        nonlocal active
        c = runs[ci]
        direction = "down" if c[0] < 0 else "up"
        key = "low" if direction == "down" else "high"
        sign = 1 if direction == "down" else -1
        checks: list[dict] = []
        report = reports.setdefault(ci, {
            'direction': direction, 'family': family, 'first_checked_index': now,
            'first_candidate_index': None, 'rejections': [],
        })
        report.update(c_start=c[1], c_end=c[2], known_index=now, closed=closed)

        def publish(evidence: dict | None) -> None:
            report['checks'] = checks
            report['status'] = ('confirmed' if closed else 'candidate') if evidence else 'blocked'
            if evidence and report['first_candidate_index'] is None:
                report['first_candidate_index'] = now
            failed = [g['gate'] for g in checks if not g['passed']]
            if failed:
                history = report['rejections']
                if history and history[-1]['through_index'] == now - 1 and history[-1]['gates'] == failed:
                    history[-1]['through_index'] = now
                else:
                    history.append({'from_index': now, 'through_index': now, 'gates': failed})

        # Never treat a left-truncated colour run as a complete A.
        checks.append({'gate': 'complete_colour_abc', 'passed': ci >= 3,
                       'values': {'observed_waves': ci + 1}})
        if ci < 3:
            publish(None)
            return
        b, a = runs[ci - 1], runs[ci - 2]
        report.update(original_a_start=a[1], original_a_end=a[2], b_start=b[1], b_end=b[2])
        a0 = a[1]
        finite = all(len(macd.get(line, [])) > c[2] and
                     all(isfinite(macd[line][i]) for i in range(a[1], c[2] + 1))
                     for line in (*lines, 'hist'))
        checks.append({'gate': 'original_abc_finite', 'passed': finite, 'values': {}})
        if finite and family == 'standard':
            for i in range(a[1], a[2] + 1):
                if any(sign * macd[line][i] >= 0 for line in lines):
                    a0 = i + 1
        axis_tail = finite and a0 <= a[2]
        checks.append({'gate': 'a_axis_suffix' if family == 'standard' else 'a_full_colour_run', 'passed': axis_tail,
                       'values': {'original_start': a[1], 'effective_start': a0, 'end': a[2]}})
        report['a_start'] = a0 if axis_tail else None
        report['a_end'] = a[2]
        evidence = (segment_evidence(bars, macd, (a0, a[2]), (c[1], c[2]), direction,
                                    whole_leg_axis=family == 'standard', whole_abc_axis=family == 'standard',
                                    whole_bc_axis=family == 'nonstandard', exact_b_pullback=True, audit=checks,
                                    allow_equal_price=True, require_dea_improvement=family == 'standard',
                                    require_price_extreme=family == 'standard',
                                    b_dif_excursion_limit=5 if revised else None)
                    if axis_tail else None)
        if axis_tail:
            pa = min(sign * getattr(bar, key) for bar in bars[a0:a[2] + 1])
            pb = min(sign * getattr(bar, key) for bar in bars[b[1]:b[2] + 1])
            pc = min(sign * getattr(bar, key) for bar in bars[c[1]:c[2] + 1])
            b_price_ok = (pc <= min(pa, pb) + 1e-6 if revised else
                          pb >= pa - 1e-6 if family == 'nonstandard' else pb > pa + 1e-6)
            checks.append({'gate': 'c_price_reaches_ab' if revised else 'b_price_not_beyond_a' if family == 'nonstandard' else 'b_price_inside_a', 'passed': b_price_ok,
                           'values': {'a_price': sign * pa, 'b_price': sign * pb,
                                      **({'c_price': sign * pc} if revised else {}),
                                      'direction': direction, 'tolerance': 1e-6}})
            if not b_price_ok:
                evidence = None
        price_extreme = min(sign * getattr(bars[i], key) for i in range(c[1], c[2] + 1))
        extreme = next(i for i in range(c[1], c[2] + 1)
                       if sign * getattr(bars[i], key) <= price_extreme + 1e-6)
        publish(evidence)
        if active is not None and (active.signal_index != extreme or evidence is None):
            active.status = "superseded"
            active.invalidated_index = now
            active.failure_audit = deepcopy({k: v for k, v in report.items() if k != 'rejections'})
            if active.signal_index != extreme:
                same_price = abs(getattr(bars[extreme], key)-getattr(bars[active.signal_index], key)) <= 1e-6
                active.failure_reason = '同价极值后移，候选锚点更新' if same_price else '价格极值被后续新极值替代'
                active.failure_audit['checks'].append({'gate': 'candidate_anchor_retained', 'passed': False,
                    'values': {'previous_price': getattr(bars[active.signal_index], key), 'price': getattr(bars[extreme], key),
                               'previous_index': active.signal_index, 'replacement_index': extreme, 'same_price': same_price}})
            else:
                failed = {g['gate'] for g in checks if not g['passed']}
                reasons = []
                for line in lines:
                    if line == 'dif' and 'dif_ac_zero_axis' in failed:
                        reasons.append('DIF 在有效 A 或 C 内触轴或跨轴')
                    if f'{line}_whole_abc_zero_axis' in failed:
                        reasons.append(f'{line.upper()} 在有效 ABC 内触轴或跨轴')
                    if f'{line}_whole_bc_zero_axis' in failed:
                        reasons.append(f'{line.upper()} 在完整 B、C 内触轴或跨轴')
                    if f'{line}_extreme_and_zero_axis' in failed:
                        witness = next(g['values'] for g in checks if g['gate'] == f'{line}_extreme_and_zero_axis')
                        if sign * witness['c_extreme'] >= 0:
                            reasons.append(f'C 段 {line.upper()} 极值不在目标零轴一侧')
                        else:
                            reasons.append(f"C 段 {line.upper()} {'最低值未高于' if direction == 'down' else '最高值未低于'} A 段")
                    if f'{line}_centre_pullback' in failed:
                        reasons.append(f'B 未使 {line.upper()} 向零轴回拉')
                if 'shrinking_same_colour_area' in failed:
                    reasons.append('C 同色柱面积不再小于 A')
                if 'strict_price_extreme' in failed:
                    reasons.append('C 未严格突破 A 的价格极值')
                if 'equal_or_new_price_extreme' in failed:
                    reasons.append('C 未达到或突破 A 的价格极值')
                if 'b_price_inside_a' in failed:
                    reasons.append('B 最低未高于 A 最低' if direction == 'down' else 'B 最高未低于 A 最高')
                if 'b_price_not_beyond_a' in failed:
                    reasons.append('B 最低低于 A 最低' if direction == 'down' else 'B 最高高于 A 最高')
                if 'c_price_reaches_ab' in failed:
                    reasons.append('C 尚未达到 A、B 的共同价格极值')
                if 'b_dif_single_excursion' in failed:
                    reasons.append('B 段 DIF 触轴／跨轴超过连续 5 根，或出现多次跨轴')
                active.failure_reason = '；'.join(reasons) or '行情或指标数据不完整，无法复核'
            active = None
        # A qualifying growing C wave is already a candidate, not a final signal.
        if evidence is not None:
            previous = min(range(a0, a[2] + 1), key=lambda i: (sign * getattr(bars[i], key), -i))
            evidence.update({"b_start": b[1], "b_end": b[2],
                             "original_a_start": a[1], "original_a_end": a[2],
                             "a_axis_trimmed": int(a0 != a[1]),
                             "a_full_comparison": int(family == 'nonstandard'),
                             "rule_version": STANDARD_WAVE_RULE_VERSION if revised else INDICATOR_RULE_VERSION,
                             "price": getattr(bars[extreme], key),
                             "previous_price": getattr(bars[previous], key),
                             "b_price": sign * pb})
            if family == 'nonstandard':
                evidence['c_price_reaches_a'] = int(price_extreme <= pa + 1e-6)
            if active is None:
                active = BC(bc_type=wave_type, bc=True, signal_index=extreme,
                            reference_index=previous, detected_index=now,
                            status="candidate", direction=direction)
                events.append(active)
            active.evidence = evidence
            two_shrinking = (now >= extreme + 2 and now - 2 >= c[1]
                             and abs(macd['hist'][now]) < abs(macd['hist'][now - 1])
                             < abs(macd['hist'][now - 2]))
            if active.preliminary_index is None and (closed or two_shrinking):
                active.preliminary_index = now
            active.msg = (f"MACD {'标准' if family == 'standard' else '非标准'}波段{'底' if direction == 'down' else '顶'}背离："
                          f"C/A {'绿' if direction == 'down' else '红'}柱面积={evidence['area_ratio']:.2f}，"
                          + (("B 最低 ≥ A 最低；" if direction == 'down' else "B 最高 ≤ A 最高；")
                             + ("价格达到前极值；" if evidence['c_price_reaches_a'] else "价格未达到前极值 · 动能减弱；")
                             if family == 'nonstandard' else
                             ("B 价格不限，C 最低 ≤ min(A、B 最低)；" if direction == 'down' else
                              "B 价格不限，C 最高 ≥ max(A、B 最高)；") if revised else
                             "B 最低 > A 最低、C 最低 ≤ A 最低；" if direction == 'down'
                             else "B 最高 < A 最高、C 最高 ≥ A 最高；")
                          + (f"段内 {'DIF、DEA' if family == 'standard' else 'DIF'} "
                             + ("谷值抬高且在零轴下方；" if direction == 'down' else "峰值降低且在零轴上方；"))
                          + ("不要求 DEA 极值改善，仍检查 DEA 零轴及 B 回拉；" if family == 'nonstandard' else "")
                          + "未据此认定中枢或一类买卖点。")
            if closed:
                active.status = "confirmed"
                active.confirmed_index = now
        if closed:
            if active is not None and active.status == "candidate":
                active.status = "superseded"
            active = None

    for now, hist in enumerate(macd["hist"]):
        if not bars[now].is_closed:
            break
        colour = 1 if hist > 0 else -1 if hist < 0 else (runs[-1][0] if runs else 0)
        if not colour:
            continue
        closed = bool(runs and colour != runs[-1][0])
        if not runs or closed:
            runs.append([colour, now, now])
        else:
            runs[-1][2] = now
        if closed:
            evaluate(now, len(runs) - 2, True)
        # Also inspect the FIRST bar of a new C, including a one-bar wave.
        evaluate(now, len(runs) - 1, False)
    _link_replacements(events)
    if revised:
        legacy_reports: list[dict] = []
        legacy = wave_events(bars, macd, diagnostics=legacy_reports, legacy_standard=True)
        old_by_c = {r['c_start']: r for r in legacy_reports}
        for report in reports.values():
            old = old_by_c.get(report['c_start'])
            if old is not None:
                report['legacy_comparison'] = {**deepcopy({k: v for k, v in old.items() if k != 'comparisons'}), 'mode': 'legacy_standard',
                    'research_only': True, 'passed': old['status'] != 'blocked',
                    'events': [dict(signal_date=bars[e.signal_index].date.isoformat(),
                                    detected_date=bars[e.detected_index].date.isoformat(), status=e.status,
                                    preliminary_date=bars[e.preliminary_index].date.isoformat() if e.preliminary_index is not None else None,
                                    failure_reason=e.failure_reason,
                                    confirmed_date=bars[e.confirmed_index].date.isoformat() if e.confirmed_index is not None else None,
                                    invalidated_date=bars[e.invalidated_index].date.isoformat() if e.invalidated_index is not None else None)
                               for e in legacy if e.evidence.get('c_start') == report['c_start']]}
        for event in events:
            e = event.evidence
            # Compare at the SAME known prefix as the candidate's last passing evidence.
            # Never use a later legacy failure to explain an earlier candidate.
            old_checks: list[dict] = []
            segment_evidence(bars, macd, (e['a_start'], e['a_end']), (e['c_start'], e['c_end']), event.direction,
                             whole_leg_axis=True, whole_abc_axis=True, allow_equal_price=True,
                             exact_b_pullback=True, audit=old_checks)
            sign = 1 if event.direction == 'down' else -1
            old_price = sign * e['b_price'] > sign * e['previous_price'] + 1e-6
            e.update(legacy_standard_passed=int(old_price and all(g['passed'] for g in old_checks)),
                     legacy_b_price_passed=int(old_price),
                     legacy_dif_axis_passed=int(not e['b_dif_excursion_bars']))
    if diagnostics is not None:
        for report in reports.values():
            report['comparisons'] = wave_rule_comparisons(bars, macd, report) if family == 'standard' else []
            if 'legacy_comparison' in report:
                report['comparisons'].append(report.pop('legacy_comparison'))
        diagnostics.extend(reports.values())
    return events


def link_wave_families(events: list[BC], bars: list[Kline]) -> None:
    """Link the same original A/B lineage, without changing either lifecycle.

    Runs only on events available in the current prefix; no inferred future C.
    IDs are dates rather than array offsets so a rolling window stays readable.
    """
    def summary(event: BC) -> dict:
        def stamp(i):
            return bars[i].date.isoformat() if i is not None else None
        return dict(type=event.bc_type.value, signal_date=stamp(event.signal_index),
                    detected_date=stamp(event.detected_index), status=event.status,
                    preliminary_date=stamp(event.preliminary_index),
                    confirmed_date=stamp(event.confirmed_index),
                    invalidated_date=stamp(event.invalidated_index), failure_reason=event.failure_reason)
    for event in events:
        event.related_events = []
        if event.bc_type not in (BCType.MACD_WAVE, BCType.MACD_WAVE_SPECIAL):
            continue
        for other in events:
            if {event.bc_type, other.bc_type} != {BCType.MACD_WAVE, BCType.MACD_WAVE_SPECIAL}:
                continue
            if event.direction == other.direction and all(
                event.evidence.get(key) is not None and event.evidence.get(key) == other.evidence.get(key)
                for key in ('a_end', 'b_start')
            ):
                event.related_events.append(summary(other))


def trend_events(bars: list[Kline], macd: dict[str, list[float]], config: ChanlunConfig
                 ) -> tuple[list[BC], list[MMD]]:
    events: list[BC] = []
    signals: list[MMD] = []
    seen: set[tuple[int, int, str]] = set()
    # Prefix replay prevents final-window centres being assigned to past buy dates.
    for now in range(5, len(bars)):
        bis = find_bis(find_fractals(merge_klines(bars[:now + 1]), config), config)
        centres = find_zss(bis, config)
        if len(centres) < 2 or not bis:
            continue
        c_bi = bis[-1]
        c0, c1 = extreme_index(c_bi.start), extreme_index(c_bi.end)
        for left, centre in zip(centres, centres[1:]):
            if not left.lines or not centre.lines or not centre.done:
                continue
            down = c_bi.direction.value == "down"
            if not (centre.zg < left.zd if down else centre.zd > left.zg):
                continue
            # A is the same-direction entry leg immediately before B, not a line in B.
            entry_index = centre.lines[0].index - 1
            if entry_index < 0 or entry_index >= len(bis):
                continue
            a_bi = bis[entry_index]
            if a_bi.direction != c_bi.direction:
                continue
            if a_bi.index < left.lines[-1].index or c_bi.index != centre.lines[-1].index + 1:
                continue
            # Reject malformed legs inherited from the legacy pen builder.
            if any((line.end.val >= line.start.val if line.direction.value == "down"
                    else line.end.val <= line.start.val)
                   for line in [a_bi, *centre.lines, c_bi]):
                continue
            if not (c_bi.low < centre.zd if down else c_bi.high > centre.zg):
                continue
            a0, a1 = extreme_index(a_bi.start), extreme_index(a_bi.end)
            identity = (a1, c1, c_bi.direction.value)
            if identity in seen:
                continue
            evidence = segment_evidence(bars, macd, (a0, a1), (c0, c1), c_bi.direction.value)
            if evidence is None:
                continue
            seen.add(identity)
            msg = (f"趋势{'底' if down else '顶'}背驰（笔中枢级）：两个中枢同向不重叠；"
                   f"C/A 同向柱面积={evidence['area_ratio']:.2f}，段内双线极值改善。")
            events.append(BC(bc_type=BCType.QS, bc=True, zs=centre, curr=c_bi, prev=a_bi,
                             signal_index=c1, reference_index=a1, detected_index=now,
                             confirmed_index=now, status="confirmed", direction=c_bi.direction.value,
                             evidence=evidence, msg=msg))
            signals.append(MMD(mmd_type=MMDType.BUY_1 if down else MMDType.SELL_1,
                               zs=centre, bi=c_bi, msg=msg, confirmed_index=now))
    return events, signals
