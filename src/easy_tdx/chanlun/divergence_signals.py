"""Causal MACD divergence events and conservative, structure-gated trend signals.

Events are evaluated on prefixes: a later bar never creates an earlier confirmation.
An indicator pivot is confirmed by a subsequent higher low / lower high.
A lower/higher extreme before confirmation supersedes the candidate.
Trend signals additionally require two disjoint same-level pen centres and completed
entry/exit legs; they deliberately do not promote ordinary MACD divergence to 1buy.
"""
from __future__ import annotations

from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.types import BC, FX, MMD, BCType, Kline, MMDType
from easy_tdx.chanlun.zs import find_zss


def extreme_index(fx: FX) -> int:
    key = "low" if fx.fx_type.value == "di" else "high"
    matches = [k.index for k in fx.k.klines if abs(getattr(k, key) - fx.val) < 1e-6]
    return matches[-1] if matches else fx.k.k_index


def indicator_events(bars: list[Kline], macd: dict[str, list[float]]) -> list[BC]:
    events: list[BC] = []
    # Independently track low and high swings, always using an intervening rebound.
    for direction, sign, key in (("down", 1, "low"), ("up", -1, "high")):
        reference: int | None = None
        pivot: int | None = None
        active: BC | None = None
        for i in range(1, len(bars)):
            if all(sign * macd[line][i] >= 0 for line in ("dif", "dea")):
                if active is not None:
                    active.status = "superseded"
                reference, pivot, active = None, None, None
                continue
            more_extreme = sign * getattr(bars[i], key) < sign * getattr(bars[i - 1], key)
            if pivot is None and more_extreme:
                pivot = i
            elif pivot is not None and sign * getattr(bars[i], key) < sign * getattr(bars[pivot], key):
                if active is not None:
                    active.status = "superseded"
                    active = None
                pivot = i
            if pivot is None:
                continue
            if i == pivot and reference is not None:
                p = reference
                price_break = sign * getattr(bars[i], key) < sign * getattr(bars[p], key) - 1e-6
                lines_improve = all(
                    sign * macd[line][i] > sign * macd[line][p] + 1e-9
                    and sign * macd[line][i] < 0 and sign * macd[line][p] < 0
                    for line in ("dif", "dea")
                )
                if price_break and lines_improve:
                    active = BC(
                        bc_type=BCType.MACD, bc=True, signal_index=i,
                        reference_index=p, detected_index=i, status="candidate",
                        direction=direction,
                        msg="MACD 指标背离：价格突破前极值，DIF、DEA 同时向零轴抬升/回落；非缠论一买/一卖。",
                        evidence={"price": getattr(bars[i], key), "previous_price": getattr(bars[p], key),
                                  "dif": macd["dif"][i], "previous_dif": macd["dif"][p],
                                  "dea": macd["dea"][i], "previous_dea": macd["dea"][p]},
                    )
                    events.append(active)
            if i > pivot and sign * getattr(bars[i], key) > sign * getattr(bars[pivot], key):
                if active is not None:
                    active.status = "confirmed"
                    active.confirmed_index = i
                if reference is None or sign * getattr(bars[pivot], key) < sign * getattr(bars[reference], key):
                    reference = pivot
                pivot, active = None, None
    return sorted(events, key=lambda e: (e.detected_index or 0, e.direction))


def segment_evidence(bars: list[Kline], macd: dict[str, list[float]],
                     a: tuple[int, int], c: tuple[int, int], direction: str) -> dict | None:
    """Compare complete, non-overlapping legs, not prices on selected dates."""
    a0, a1 = a
    c0, c1 = c
    if not (0 <= a0 <= a1 < c0 <= c1 < len(bars)):
        return None
    down = direction == "down"
    sign = 1 if down else -1
    price_key = "low" if down else "high"
    pa = min(sign * getattr(k, price_key) for k in bars[a0:a1 + 1])
    pc = min(sign * getattr(k, price_key) for k in bars[c0:c1 + 1])
    area_a = sum(max(0, -sign * h) for h in macd["hist"][a0:a1 + 1])
    area_c = sum(max(0, -sign * h) for h in macd["hist"][c0:c1 + 1])
    if pc >= pa - 1e-6 or not (0 < area_c < area_a):
        return None
    evidence = {"a_start": a0, "a_end": a1, "c_start": c0, "c_end": c1,
                "a_area": area_a, "c_area": area_c, "area_ratio": area_c / area_a}
    for line in ("dif", "dea"):
        av = min(sign * v for v in macd[line][a0:a1 + 1])
        cv = min(sign * v for v in macd[line][c0:c1 + 1])
        # Segment troughs improve, both are on the trend side of zero.
        if not av < cv < 0:
            return None
        # The intervening centre must have pulled both lines toward zero.
        if max(sign * v for v in macd[line][a1:c0 + 1]) <= av:
            return None
        evidence[f"a_{line}_extreme"] = sign * av
        evidence[f"c_{line}_extreme"] = sign * cv
    return evidence


def wave_events(bars: list[Kline], macd: dict[str, list[float]]) -> list[BC]:
    """Green/red/green (and mirrored) waves; confirm only on opposite colour.

    Exact zero bars extend the preceding wave; initial zero bars are ignored.
    The first observed wave is not a reference because its beginning may be cut off.
    Candidate evidence is updated only while the candidate is active, never after
    confirmation. Each replaced/invalidated candidate remains in the event log.
    """
    runs: list[list[int]] = []  # sign, start, end
    events: list[BC] = []
    active: BC | None = None
    for now, hist in enumerate(macd["hist"]):
        colour = 1 if hist > 0 else -1 if hist < 0 else (runs[-1][0] if runs else 0)
        if not colour:
            continue
        closed = bool(runs and colour != runs[-1][0])
        if not runs or closed:
            runs.append([colour, now, now])
        else:
            runs[-1][2] = now
        ci = len(runs) - (2 if closed else 1)
        if ci < 3:  # A must be a fully observed wave, not runs[0].
            continue
        c, b, a = runs[ci], runs[ci - 1], runs[ci - 2]
        direction = "down" if c[0] < 0 else "up"
        key = "low" if direction == "down" else "high"
        sign = 1 if direction == "down" else -1
        extreme = min(range(c[1], c[2] + 1), key=lambda i: (sign * getattr(bars[i], key), -i))
        previous = min(range(a[1], a[2] + 1), key=lambda i: (sign * getattr(bars[i], key), -i))
        evidence = segment_evidence(bars, macd, (a[1], a[2]), (c[1], c[2]), direction)
        if active is not None and (active.signal_index != extreme or evidence is None):
            active.status = "superseded"
            active = None
        shrinking = c[2] > c[1] and abs(hist) < abs(macd["hist"][now - 1])
        if evidence is not None and (closed or shrinking):
            evidence.update({"b_start": b[1], "b_end": b[2],
                             "price": getattr(bars[extreme], key),
                             "previous_price": getattr(bars[previous], key)})
            if active is None:
                active = BC(bc_type=BCType.MACD_WAVE, bc=True, signal_index=extreme,
                            reference_index=previous, detected_index=now,
                            status="candidate", direction=direction)
                events.append(active)
            active.evidence = evidence
            active.msg = (f"MACD 波段{'底' if direction == 'down' else '顶'}背离："
                          f"C/A 柱面积={evidence['area_ratio']:.2f}，价格突破前段极值，"
                          "段内 DIF、DEA 极值改善；未据此认定中枢或一类买卖点。")
            if closed:
                active.status = "confirmed"
                active.confirmed_index = now
        if closed:
            if active is not None and active.status == "candidate":
                active.status = "superseded"
            active = None
    return events


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
