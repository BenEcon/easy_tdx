"""Causal, versioned ownership domains with quarantined engineering recursion.

An ownership domain is bookkeeping, NOT a higher centre or a completed type.
Overlapping claims share one domain so sources are never spent twice. Local
completed types can build parents inside it; parent gates remain independent.
The old flat interpretation remains a separate, unchanged historical view.
"""
from copy import deepcopy
from itertools import groupby

from easy_tdx.chanlun.engineering_consolidations import consolidation_candidates
from easy_tdx.chanlun.engineering_trends import _candidates, _hierarchy
from easy_tdx.chanlun.extension_recursion import centre_extension_proof
from easy_tdx.chanlun.ownership_conflicts import ownership_conflict
from easy_tdx.chanlun.ownership_history import OwnershipHistoryMode, ownership_history_summary
from easy_tdx.chanlun.structure import confirmed_segment_prefix, iter_structural_steps
from easy_tdx.chanlun.types import XD, Kline

RULE = 'layered_internal_ownership_v1'


def _claim_events(items: list[XD]) -> dict[int, list[dict]]:
    """Detached snapshots, including all admissions after a promotion proof."""
    lookup = {item.index: item for item in items}
    events: dict[int, list[dict]] = {}
    previous = {}
    for unit, centre, prior in iter_structural_steps(items):
        if centre is None:
            continue
        claims = []
        proof = centre_extension_proof(centre, lookup)
        if proof is not None:
            claims.append({'key': f'promotion:{centre.seed_segments[0]}',
                           'kind': 'promotion', 'sources': list(centre.member_segments),
                           'proof_id': proof['id']})
        if prior is not None and centre.relation_current in ('overlapping', 'expansion_candidate'):
            claims.append({'key': f'expansion:{prior.seed_segments[0]}:{centre.seed_segments[0]}',
                           'kind': 'expansion', 'sources': list(range(
                               prior.member_segments[0], centre.member_segments[-1] + 1)),
                           'proof_id': None})
        for claim in claims:
            if previous.get(claim['key']) != claim:
                previous[claim['key']] = claim
                events.setdefault(unit.confirmed_index, []).append(claim)
    return events


def _domains(claims: dict[str, dict]) -> list[dict]:
    """Union overlapping (not merely adjacent) claims; never infer completion."""
    domains = []
    for claim in sorted(claims.values(), key=lambda c: (c['sources'][0], c['sources'][-1])):
        if not domains or claim['sources'][0] > domains[-1]['sources'][-1]:
            domains.append({'sources': list(claim['sources']), 'claims': [claim['key']]})
        else:
            domain = domains[-1]
            domain['sources'] = list(range(domain['sources'][0], max(
                domain['sources'][-1], claim['sources'][-1]) + 1))
            domain['claims'].append(claim['key'])
    return domains


def _frontier(levels: list[dict]) -> list[str]:
    """A parent replaces its children on the effective internal input frontier."""
    active = {}
    for level in levels:
        for record in level['types']:
            for child in record['child_ids']:
                active.pop(child, None)
            active[record['id']] = record
    return [record['id'] for record in sorted(
        active.values(), key=lambda r: r['source_segment_indices'][0])]


def layered_movement_ownership(segments: list[XD], bars: list[Kline], macd: dict,
                               flat: dict, *, nested: bool = False,
                               ownership_history: OwnershipHistoryMode = 'full') -> dict:
    """Publish immutable as-of owner revisions, without admitting trading inputs.

    Base completion time stays original. Internal availability is the later of
    completion and actual ownership. Every revision is calculated from a real
    confirmation batch; future owner merges cannot backdate a parent. A domain
    may contain gaps in completed child coverage, and those gaps split chains.
    Summary delivery retains full active revisions only, collecting detached
    replay addresses as each revision is created. Replaced detail is no longer
    needed by the algorithm; it must not accumulate just to be discarded later.
    """
    if ownership_history not in ('full', 'summary'):
        raise ValueError('ownership_history must be full or summary')
    items = confirmed_segment_prefix(segments, len(bars))
    events = _claim_events(items)
    result = {'rule': RULE, 'scope': 'internal_engineering_ownership',
              'natural_type_recursion_ready': False, 'versions': [], 'current_owner_ids': [],
              'external_m1_ids': [], 'external_unresolved_segment_indices': [],
              'accepted_segment_count': len(items),
              'rejected_suffix_count': len(segments) - len(items)}
    if nested:
        result['rule'] = 'layered_recursive_ownership_v2'
    if ownership_history == 'summary':
        result.update(history_format='summary_v1', history_summaries=[])
    flat_m1 = flat['levels'][0]['types'] if flat.get('levels') else []
    if not events:
        result['external_m1_ids'] = [r['id'] for r in flat_m1]
        covered = {i for r in flat_m1 for i in r['source_segment_indices']}
        result['external_unresolved_segment_indices'] = [s.index for s in items
                                                          if s.index not in covered]
        return result
    local = [{**c, 'kind': 'trend'} for c in _candidates(items, bars, macd, internal=True)]
    local += consolidation_candidates(items, bars, macd)
    for candidate in local:
        events.setdefault(candidate['known_index'], [])
    scan_cache = None
    if nested:
        from easy_tdx.chanlun.nested_recursion import _NestedScanCache
        scan_cache = _NestedScanCache(bars, macd)
    claims, admitted, active = {}, {}, []
    for known, batch in groupby(items, key=lambda item: item.confirmed_index):
        # Materialize batch so every same-time claim is considered together.
        list(batch)
        if known not in events:
            continue
        for claim in events[known]:
            claims[claim['key']] = claim
            for source in claim['sources']:
                admitted.setdefault(source, known)
        next_active = []
        domains = _domains(claims)
        # Resolve the whole batch before inspecting any candidate. A witness
        # may move to another domain while this domain's own claims stay fixed.
        source_owners = {source: ordinal for ordinal, domain in enumerate(domains)
                         for source in domain['sources']} if nested else {}
        for ordinal, domain in enumerate(domains):
            sources = domain['sources']
            source_set = set(sources)
            predecessors = [v for v in active
                            if source_set.intersection(v['source_segment_indices'])]
            # Joining two owners is a new context, not an old completed parent.
            context_known = (predecessors[0]['context_known_index']
                             if len(predecessors) == 1 else known)
            seed, blocked, blocked_local = [], [], []
            for candidate in local:
                if (candidate['known_index'] > known
                        or candidate['start_unit_index'] < sources[0]
                        or candidate['end_unit_index'] > sources[-1]):
                    continue
                witness_owner = source_owners.get(candidate['opposite_unit_index'])
                if witness_owner is not None and witness_owner != ordinal:
                    blocked.append({
                        'source_unit_ids': [f'segment:{i}' for i in range(
                            candidate['start_unit_index'], candidate['end_unit_index'] + 1)],
                        'original_known_index': candidate['known_index'],
                        'reason': 'opposite_witness_owned_by_another_domain'})
                    blocked_local.append(candidate)
                    continue
                membership = max(admitted[i] for i in range(
                    candidate['start_unit_index'], candidate['end_unit_index'] + 1))
                seed.append({**candidate, 'original_known_index': candidate['known_index'],
                             'ownership_known_index': max(context_known, membership),
                             'known_index': max(candidate['known_index'],
                                                context_known, membership)})
            signature = (sources, domain['claims'], [(c['kind'], c['start_unit_index'],
                         c['end_unit_index'], c['known_index']) for c in seed])
            if nested:
                signature += (blocked,)
            if len(predecessors) == 1 and predecessors[0]['_signature'] == signature:
                next_active.append(predecessors[0])
                continue
            owner_id = f'owner:{sources[0]}:{sources[-1]}:at:{known}'
            hierarchy = _hierarchy([s for s in items if s.confirmed_index <= known],
                                   bars[:known + 1], macd, mixed=True,
                                   internal_seed=seed, owner_id=owner_id, nested=nested,
                                   scan_cache=scan_cache)
            levels = hierarchy['levels']
            covered = {i for level in levels[:1] for r in level['types']
                       for i in r['source_segment_indices']}
            if levels:
                levels[0]['input_count'] = len(sources)
                levels[0]['unresolved_input_ids'] = [f'segment:{i}' for i in sources
                                                    if i not in covered]
            version = {'id': owner_id, 'known_index': known, 'context_known_index': context_known,
                       'source_segment_indices': sources,
                       'previous_owner_ids': [v['id'] for v in predecessors],
                       'claims': [deepcopy(claims[key]) for key in domain['claims']],
                       'member_admissions': [{'segment_index': i, 'admitted_index': admitted[i]}
                                             for i in sources],
                       'levels': levels, 'frontier_ids': _frontier(levels),
                       'unresolved_segment_indices': [i for i in sources if i not in covered],
                       'highest_completed_internal_level': len(levels),
                       'natural_type_complete': False, 'eligible_for_external_recursion': False,
                       'structure_layers': hierarchy['structure_layers'], '_signature': signature}
            if nested:
                # Enrich output only, after the unchanged decision signature.
                # Do not mutate blocked: it remains part of the stored signature.
                base_records = ({s.index: {'id': f'segment:{s.index}',
                                          'source_segment_indices': [s.index],
                                          'known_index': s.confirmed_index} for s in items}
                                if blocked else {})
                blocked_details = [{**entry, 'ownership_conflict': ownership_conflict(
                    candidate, base_records, 0, domains)}
                    for entry, candidate in zip(blocked, blocked_local, strict=True)]
                version['nested_owners'] = hierarchy['nested_owners']
                version['blocked_ownership_candidates'] = [
                    *blocked_details, *hierarchy['blocked_ownership_candidates']]
            if ownership_history == 'summary':
                result['history_summaries'].append(ownership_history_summary(version))
            else:
                result['versions'].append(version)
            next_active.append(version)
        active = next_active
    if ownership_history == 'summary':
        # Legacy projection filters the chronological history, whereas active
        # owners are in spatial order. An unchanged neighbour may be older.
        by_id = {version['id']: version for version in active}
        result['versions'] = [by_id[entry['id']] for entry in result['history_summaries']
                              if entry['id'] in by_id]
    result['current_owner_ids'] = [v['id'] for v in active]
    protected = {i for owner in active for i in owner['source_segment_indices']}
    external = [r for r in flat_m1 if not protected.intersection(r['source_segment_indices'])]
    if nested:
        # A witness is not geometric coverage, but its current ownership still
        # constrains eligibility. Keep the old flat record as history only.
        external = [r for r in external if r['opposite_unit_index'] not in protected]
    result['external_m1_ids'] = [r['id'] for r in external]
    covered = protected | {i for r in external for i in r['source_segment_indices']}
    result['external_unresolved_segment_indices'] = [s.index for s in items
                                                     if s.index not in covered]
    for version in result['versions']:
        del version['_signature']
    return deepcopy(result)
