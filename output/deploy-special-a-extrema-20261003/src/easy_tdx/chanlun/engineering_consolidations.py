"""Approved single-centre engineering closure, not a natural-completion theorem.

A is a complete entering unit, B starts AFTER A and owns at least three units,
and C leaves B in A's direction. The next confirmed opposite unit is a witness,
not an owned source. All gates use evidence available at that confirmation.
"""
from easy_tdx.chanlun import candidate_audit as audit
from easy_tdx.chanlun.anchors import extreme_index
from easy_tdx.chanlun.divergence_signals import segment_evidence
from easy_tdx.chanlun.expansion_regrouping import _endpoint_checks
from easy_tdx.chanlun.extension_recursion import centre_extension_proof, promoted_member_times
from easy_tdx.chanlun.structure import iter_structural_steps
from easy_tdx.chanlun.types import XD, Kline


def conflict_member_times(items: list[XD]) -> dict[int, int]:
    """Conservative original-chain ownership, including expansion connectors.

    A local restart cannot bypass a known overlapping/expanding pair. Later
    admissions become protected only when admitted; future conflicts cannot
    retroactively remove an earlier completion. No pending departure is owned.
    """
    protected = promoted_member_times(items)
    for current, centre, prior in iter_structural_steps(items):
        if (centre is None or prior is None
                or centre.relation_current not in ('overlapping', 'expansion_candidate')):
            continue
        for index in range(prior.member_segments[0], centre.member_segments[-1] + 1):
            protected[index] = min(protected.get(index, current.confirmed_index),
                                   current.confirmed_index)
    return protected


def consolidation_candidates(items: list[XD], bars: list[Kline], macd: dict,
                             *, trace: list | None = None) -> list[dict]:
    if not all(macd.get(key) for key in ('dif', 'dea', 'hist')):
        for start, first in enumerate(items) if trace is not None else ():
            audit.pruned(trace, 'consolidation', first, items[start:],
                         'macd_series_missing', first.confirmed_index)
        return []
    lookup = {s.index: s for s in items}
    candidates = []
    for start, entry in enumerate(items):
        audit.decision(audit.attempt(trace, 'consolidation', entry, entry),
                       'no_following_centre_units')
        centre = pending = None
        pending_row = None
        found_rows = []
        found = []
        invalid_at = terminal_at = None
        low, high = entry.low, entry.high
        for current, active, _ in iter_structural_steps(items[start + 1:]):
            if terminal_at is not None and current.confirmed_index > terminal_at:
                audit.pruned(trace, 'consolidation', entry,
                             [s for s in items if s.index >= current.index],
                             'start_extreme_irrecoverable', terminal_at)
                break
            row = audit.attempt(trace, 'consolidation', entry, current)
            low, high = min(low, current.low), max(high, current.high)
            if active is not None:
                if centre is None:
                    centre = active
                if (active is not centre or centre.seed_segments[0] != entry.index + 1
                        or centre_extension_proof(centre, lookup) is not None):
                    invalid_at = current.confirmed_index
                    reason = ('multiple_centres_in_consolidation' if active is not centre else
                              'centre_not_immediately_after_entry'
                              if centre.seed_segments[0] != entry.index + 1 else 'centre_upgraded')
                    audit.decision(row, reason, seed_segments=list(centre.seed_segments))
                    audit.invalidate([*found_rows, pending_row], invalid_at)
                    audit.pruned(trace, 'consolidation', entry,
                                 [s for s in items if s.index > current.index],
                                 'invalidated_start_suffix', invalid_at)
                    break
            if pending is not None:
                if current.direction != entry.direction:
                    found.append({**pending, 'known_index': current.confirmed_index,
                                  'opposite_unit_index': current.index,
                                  'opposite_start_index': extreme_index(current.start),
                                  'opposite_end_index': extreme_index(current.end)})
                    audit.confirmed(pending_row, current)
                    found_rows.append(pending_row)
                else:
                    audit.decision(pending_row, 'next_unit_not_opposite', unit_index=current.index)
                pending = None
                pending_row = None
            geometry = {'start_value': entry.start.val, 'end_value': current.end.val,
                        'direction': entry.direction.value, 'low': low, 'high': high}
            if not _endpoint_checks(geometry)[2]:
                terminal_at = current.confirmed_index
                audit.decision(row, 'start_not_directional_extreme', **geometry)
                continue
            if (centre is None or centre.state != 'departed'
                    or centre.departure_segment != current.index
                    or current.direction != entry.direction
                    or not _endpoint_checks(geometry)[3]):
                audit.decision(row, 'structure_gates_not_met',
                               centre_exists=centre is not None,
                               centre_departed=centre is not None and centre.state == 'departed',
                               current_is_departure=(centre is not None
                                                     and centre.departure_segment == current.index),
                               same_direction=current.direction == entry.direction,
                               end_is_extreme=_endpoint_checks(geometry)[3])
                continue
            evidence = segment_evidence(
                bars, macd, (extreme_index(entry.start), extreme_index(entry.end)),
                (extreme_index(current.start), extreme_index(current.end)),
                current.direction.value, **({'audit': row['macd_checks']} if row is not None else {}))
            if evidence is None:
                audit.decision(row, 'macd_gates_not_met')
                continue
            pending = {
                **geometry, 'kind': 'consolidation',
                'start_unit_index': entry.index, 'end_unit_index': current.index,
                'start_index': extreme_index(entry.start), 'end_index': extreme_index(current.end),
                'divergence_known_index': current.confirmed_index,
                'a_unit_index': entry.index, 'c_unit_index': current.index,
                'macd_evidence': evidence,
                'centres': [{'source_unit_indices': list(centre.member_segments),
                             'zd': centre.zd, 'zg': centre.zg, 'low': centre.dd, 'high': centre.gg,
                             'formed_index': centre.formed_index}],
            }
            pending_row = row
            audit.pending(row, evidence)
        candidates.extend(c for c in found if invalid_at is None or c['known_index'] < invalid_at)
    return candidates
