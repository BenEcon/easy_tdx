"""Prefix-replayed signals on the confirmed-segment base layer.

These research signals are separate from the legacy pen-proxy API. Higher-level
recursive types are not inferred from the selected chart frequency.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from easy_tdx.chanlun.divergence_signals import extreme_index, segment_evidence
from easy_tdx.chanlun.structure import confirmed_segment_prefix, find_structural_centres
from easy_tdx.chanlun.types import BC, MMD, XD, BCType, Direction, Kline, MMDType


@dataclass
class StructuralSignal:
    signal_type: str
    segment_index: int
    centre_index: int
    signal_index: int
    confirmed_index: int
    evidence: dict = field(default_factory=dict)
    source: str = 'confirmed_segment_base_v1'


def structure_signals(segments: list[XD], bars: list[Kline],
                      macd: dict[str, list[float]]) -> list[StructuralSignal]:
    """Replay completed segments so later centres cannot classify an earlier signal.

    One: separated envelopes, same-direction entry/departure, MACD filter.
    Two: exactly the first completed return after that one; weaker returns allowed
    and explicitly classified. Three: first completed return outside a fixed core.
    Two and three are independent labels, not mutually exclusive branches.
    """
    segments = confirmed_segment_prefix(segments, bar_count=len(bars))
    result: list[StructuralSignal] = []
    seen: set[tuple[str, int, int]] = set()
    lookup = {s.index: s for s in segments}

    def add(kind: str, line: XD, centre: int, evidence: dict, known: int) -> None:
        key = (kind, line.index, centre)
        if key in seen:
            return
        seen.add(key)
        result.append(StructuralSignal(kind, line.index, centre, extreme_index(line.end),
                                       known, evidence))

    for n in range(3, len(segments) + 1):
        current = segments[n - 1]
        if current.confirmed_index is None:
            break
        known = current.confirmed_index
        prefix = segments[:n]
        centres = find_structural_centres(prefix)
        # First returns relative to already observed first signals.
        for first in list(result):
            if first.signal_type not in ('1buy', '1sell'):
                continue
            if current.index != first.segment_index + 2 or known < first.confirmed_index:
                continue
            down = first.signal_type == '1buy'
            wanted = Direction.DOWN if down else Direction.UP
            previous = lookup.get(current.index - 1)
            if current.direction != wanted or previous is None or previous.direction == wanted:
                continue
            base = lookup[first.segment_index]
            if (previous.start.k.index != base.end.k.index
                    or previous.start.val != base.end.val
                    or current.start.k.index != previous.end.k.index
                    or current.start.val != previous.end.val):
                continue
            weaker = current.end.val < base.end.val if down else current.end.val > base.end.val
            add('2buy' if down else '2sell', current, first.centre_index,
                {'first_segment': first.segment_index,
                 'first_confirmed_index': first.confirmed_index,
                 'centre_segment_count': first.evidence['centre_segment_count'],
                 'rebound_segment': previous.index, 'return_segment': current.index,
                 'strength': 'weak_new_extreme' if weaker else 'held_first_extreme'}, known)

        for i, centre in enumerate(centres):
            if centre.state == 'exited' and centre.return_segment == current.index:
                up = centre.departure_direction == 'up'
                add('3buy' if up else '3sell', current, centre.index,
                    {'departure_segment': centre.departure_segment,
                     'return_segment': current.index, 'zd': centre.zd, 'zg': centre.zg,
                     'centre_segment_count': len(centre.member_segments),
                     'formed_index': centre.formed_index, 'first_return': True}, known)
            if centre.state != 'departed' or centre.departure_segment != current.index:
                continue
            previous_centre = centres[i - 1] if i else None
            down = current.direction == Direction.DOWN
            separated = previous_centre is not None and (
                centre.gg < previous_centre.dd if down else centre.dd > previous_centre.gg)
            a_index = centre.seed_segments[0] - 1
            entry = lookup.get(a_index)
            if entry is None or entry.direction != current.direction:
                continue
            evidence = segment_evidence(
                bars, macd, (extreme_index(entry.start), extreme_index(entry.end)),
                (extreme_index(current.start), extreme_index(current.end)), current.direction.value)
            if evidence is None:
                continue
            evidence.update({'a_segment': entry.index, 'c_segment': current.index,
                             'b_segments': list(centre.member_segments),
                             'previous_centre': previous_centre.index if previous_centre else None,
                             'centre': centre.index, 'zd': centre.zd, 'zg': centre.zg,
                             'centre_segment_count': len(centre.member_segments),
                             'envelopes_separated': separated,
                             'classification': 'trend' if separated else 'consolidation',
                             'macd_filter': 'area_and_dual_lines'})
            kind = ('1buy' if down else '1sell') if separated else (
                'consolidation_bottom_divergence' if down else 'consolidation_top_divergence')
            add(kind, current, centre.index, evidence, known)
    return sorted(result, key=lambda s: (s.confirmed_index, s.signal_type, s.centre_index))


def to_chart_signals(
    events: list[StructuralSignal], segments: list[XD],
) -> tuple[list[MMD], list[BC]]:
    """One authoritative source for chart, factor, radar and backtest consumers."""
    lines = {s.index: s for s in segments}
    mmds: list[MMD] = []
    divergences: list[BC] = []
    names = {'1buy': '一买', '2buy': '二买', '3buy': '三买',
             '1sell': '一卖', '2sell': '二卖', '3sell': '三卖'}
    for event in events:
        current = lines[event.segment_index]
        if event.signal_type in names:
            note = '（弱势：回试突破首个极值）' if (
                event.evidence.get('strength') == 'weak_new_extreme') else ''
            mmds.append(MMD(MMDType(event.signal_type), bi=current,
                            msg=f"线段基础{names[event.signal_type]}：结构确认{note}",
                            confirmed_index=event.confirmed_index,
                            source=event.source, evidence=event.evidence.copy()))
        trend = event.signal_type in ('1buy', '1sell')
        consolidation = event.signal_type.startswith('consolidation_')
        if not trend and not consolidation:
            continue
        entry = lines[event.evidence['a_segment']]
        evidence = {key: value for key, value in event.evidence.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)}
        members = event.evidence['b_segments']
        evidence.update({'b_start': extreme_index(lines[members[0]].start),
                         'b_end': extreme_index(lines[members[-1]].end)})
        side = '底' if current.direction == Direction.DOWN else '顶'
        label = '趋势' if trend else '盘整力度'
        divergences.append(BC(
            bc_type=BCType.QS if trend else BCType.PZ, bc=True, curr=current, prev=entry,
            signal_index=event.signal_index, reference_index=extreme_index(entry.end),
            detected_index=event.confirmed_index, confirmed_index=event.confirmed_index,
            status='confirmed', direction=current.direction.value, evidence=evidence,
            msg=f'线段基础{label}{side}背驰（MACD过滤）；'
                + ('两中枢外围分离。' if trend else '不据此认定趋势一类买卖点。')))
    return mmds, divergences
