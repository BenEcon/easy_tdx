"""Finite exhaustive search under the approved fixed-base engineering grammar.

At each layer, explore EVERY disjoint candidate subset, including the empty
subset (all remaining inputs unresolved). Candidates are generated afresh on
each lower-layer interpretation; ownership and reverse witnesses are not reused
across branches. A binary DFS path is sufficient to resume without retaining an
exponentially large frontier. There is no beam, random sampling or depth limit.
"""

from easy_tdx.chanlun.released_recursion import released_movement_snapshot

GRAMMAR = "fixed_base_all_candidate_subsets_v1"


class SubsetTraversal:
    def __init__(self, path=()):
        if any(type(bit) is not int or bit not in (0, 1) for bit in path):
            raise ValueError("invalid search path")
        self.path = list(path)
        self.trail = []

    def __call__(self, candidates):
        selected = []
        # Same stable candidate ordering as the default selector. Include-first
        # therefore yields the default interpretation as the very first leaf.
        for candidate in sorted(
            candidates, key=lambda c: (c["known_index"], c["start_unit_index"], c["end_unit_index"])
        ):
            if any(
                candidate["start_unit_index"] <= old["end_unit_index"]
                and old["start_unit_index"] <= candidate["end_unit_index"]
                for old in selected
            ):
                continue  # Including it is impossible in this subset, not a heuristic prune.
            position = len(self.trail)
            include = self.path[position] if position < len(self.path) else 1
            self.trail.append(include)
            if include:
                selected.append(candidate)
        return sorted(selected, key=lambda c: c["start_unit_index"])

    def next_path(self):
        if len(self.path) > len(self.trail):
            raise ValueError("search path does not belong to this snapshot")
        for i in range(len(self.trail) - 1, -1, -1):
            if self.trail[i] == 1:
                return [*self.trail[:i], 0]
        return None


def exhaustive_leaf(segments, bars, macd, path=(), *, trace=False):
    selector = SubsetTraversal(path)
    audit = {} if trace else None
    snapshot = released_movement_snapshot(segments, bars, macd, _selector=selector, _audit=audit)
    next_path = selector.next_path()
    return {"snapshot": snapshot, "path": selector.trail, "next_path": next_path, "audit": audit}
