"""Optional observations emitted by the actual candidate detectors, never a second detector."""

from copy import deepcopy


def attempt(trace, kind, first, current):
    if trace is None:
        return None
    row = {
        "kind": kind,
        "start_unit_index": first.index,
        "end_unit_index": current.index,
        "known_index": current.confirmed_index,
        "outcome": "not_evaluated",
        "reason": None,
        "details": {},
        "macd_checks": [],
    }
    trace.append(row)
    return row


def decision(row, reason, **details):
    if row is not None:
        row.update(reason=reason, details=deepcopy(details), outcome="rejected")


def pending(row, evidence):
    if row is not None:
        row.update(
            outcome="pending", reason="reverse_not_yet_confirmed", details=deepcopy(evidence)
        )


def confirmed(row, witness):
    if row is not None:
        row.update(
            outcome="candidate",
            reason=None,
            confirmed_index=witness.confirmed_index,
            opposite_unit_index=witness.index,
        )


def invalidate(rows, known):
    for row in rows:
        if row is not None and (row.get("confirmed_index", known) >= known):
            decision(row, "same_batch_structure_invalidated", invalidated_index=known)


def pruned(trace, kind, first, remaining, reason, known):
    if trace is not None:
        for current in remaining:
            decision(attempt(trace, kind, first, current), reason, failed_at_index=known)
