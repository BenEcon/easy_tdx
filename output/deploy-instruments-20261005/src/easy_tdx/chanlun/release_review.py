"""Research-only alternative selections and diffs of independently rebuilt snapshots."""
from copy import deepcopy

from easy_tdx.chanlun.engineering_trends import _select_owned_candidates

POLICIES = ('earliest', 'widest', 'latest')


def select_for_review(candidates, policy):
    if policy not in POLICIES:
        raise ValueError('unknown research selection policy')
    if policy == 'earliest':
        return _select_owned_candidates(candidates)
    # Same individually qualified candidates; only ownership of overlapping
    # alternative spans changes. The caller must re-run every higher-level gate.
    def priority(c):
        width = c['end_unit_index'] - c['start_unit_index']
        primary = -width if policy == 'widest' else -c['known_index']
        return primary, c['known_index'], c['start_unit_index'], c['end_unit_index']
    selected = []
    for candidate in sorted(candidates, key=priority):
        if not any(candidate['start_unit_index'] <= old['end_unit_index']
                   and old['start_unit_index'] <= candidate['end_unit_index'] for old in selected):
            selected.append(candidate)
    return sorted(selected, key=lambda c: c['start_unit_index'])


def review_state(snapshot):
    """Compact state for diffing; never derive past states from current dates."""
    state = {}
    for layer in snapshot['levels']:
        for record in layer['types']:
            state[record['id']] = {
                'kind': 'movement', 'level': record['level'],
                'source_segment_indices': record['source_segment_indices'],
                'start_index': record['start_index'], 'end_index': record['end_index'],
                'original_known_index': record['original_known_index'],
                'current_placement': record['current_placement'],
                'required_domain_ids': record['required_domain_ids'],
                'eligible_for_external_recursion': record['eligible_for_external_recursion'],
                'on_frontier': record['on_frontier'],
                'represented_by_id': record['represented_by_id'],
            }
    for domain in snapshot['domains']:
        state[domain['id']] = {'kind': 'domain', **domain}
    return deepcopy(state)


def review_changes(before, after, index, date):
    changes = []
    for identity in sorted(before.keys() | after.keys()):
        previous, current = before.get(identity), after.get(identity)
        if previous != current:
            changes.append({'id': identity, 'index': index, 'date': date,
                            'change': 'added' if previous is None else (
                                'removed' if current is None else 'changed'),
                            'before': previous, 'after': current})
    return changes
