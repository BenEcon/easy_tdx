"""Link existing M1 completions to exact research partitions, never authorize them.

This consumes the selected mixed interpretation calculated from the SAME input
snapshot. A historical match is not current source ownership or completion of
the surrounding regrouping. Natural-completion blockers remain untouched.
"""
from copy import deepcopy
from math import isclose

from easy_tdx.chanlun.engineering_trends import MOVEMENT_RULE

LINK_RULE = 'exact_historical_engineering_completion_v1'


def link_engineering_completions(versions: dict, hierarchy: dict) -> dict:
    """Return an isolated enrichment; no re-search, re-ranking or state changes."""
    result = deepcopy(versions)
    records = {}
    if (hierarchy.get('scope') == 'engineering_mixed_movements'
            and hierarchy.get('rule') == MOVEMENT_RULE):
        for level in hierarchy['levels']:
            if level['level'] != 1:
                continue
            for record in level['types']:
                if (record.get('level') == 1 and record.get('rule') == MOVEMENT_RULE
                        and record.get('engineering_complete') is True
                        and record.get('eligible_for_movement_recursion') is True
                        and record.get('theory_equivalence_claim') is False):
                    key = tuple(record['source_segment_indices'])
                    # Ambiguity must not arbitrarily select one explanation.
                    records[key] = record if key not in records else None

    def match(part: dict, audit: dict, known: int) -> dict | None:
        source = part['source_segment_indices']
        record = records.get(tuple(source))
        kind = 'trend' if part.get('component_kind') == 'trend_candidate' else 'consolidation'
        if (not record or not source or source != list(range(source[0], source[-1] + 1))
                or record['kind'] != kind or record['direction'] != part['direction']
                or record['id'] != f'movement:{kind}:L1:{source[0]}:{source[-1]}'
                or record['start_index'] != part['start_index']
                or record['end_index'] != part['end_index']
                or not part['known_index'] <= record['known_index'] <= known
                or record['opposite_id'] != f'segment:{source[-1] + 1}'
                or audit['opposite_segment_index'] != source[-1] + 1
                or audit['opposite_known_index'] != record['known_index']
                or not audit['start_is_extreme'] or not audit['end_is_extreme']
                or any(not isclose(record[key], part[key], rel_tol=1e-9, abs_tol=1e-8)
                       for key in ('start_value', 'end_value', 'low', 'high'))):
            return None
        return {
            'rule': LINK_RULE, 'movement_rule': MOVEMENT_RULE,
            'status': 'historical_engineering_match', 'movement_id': record['id'],
            'kind': kind, 'level': 1, 'direction': record['direction'],
            'source_segment_indices': list(source),
            'start_index': record['start_index'], 'end_index': record['end_index'],
            'start_value': record['start_value'], 'end_value': record['end_value'],
            'known_index': record['known_index'], 'as_of_index': known,
            'opposite_id': record['opposite_id'],
            'macd_evidence': deepcopy(record['macd_evidence']),
            'natural_type_complete': False, 'eligible_for_recursive_input': False,
        }

    def enrich(revision: dict, audit: dict) -> None:
        # Bind both the partition and its as-of time. Never reuse the current
        # audit in historical versions or carry a match by A/B/C ordinal alone.
        if (audit['interpretation_id'] != revision['id']
                or len(audit['parts']) != len(revision['parts'])):
            return
        for part, item in zip(revision['parts'], audit['parts'], strict=True):
            item['engineering_completion'] = (
                match(part, item, audit['as_of_index'])
                if item['source_segment_indices'] == part['source_segment_indices'] else None)

    for case in result['cases']:
        for revision in case['revisions']:
            enrich(revision, revision['completion_audit'])
        current = next((r for r in case['revisions']
                        if r['id'] == case['current_revision_id']), None)
        if current is not None:
            enrich(current, case['completion_audit'])
    return result
