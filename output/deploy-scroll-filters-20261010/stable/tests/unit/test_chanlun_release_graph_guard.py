"""A coherent source/confirmation graph is required for the release inspector."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from easy_tdx.chanlun.released_recursion import released_movement_snapshot
from tests.unit.test_chanlun_released_recursion import lift_fixture, release_fixture

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node needed for graph guard")
MUTATIONS = {
    "direction": "parent.direction = parent.direction === 'up' ? 'down' : 'up';",
    "fractional_end": "parent.end_index += .5;",
    "kind": "parent.kind = 'unverified';",
    "record_rule": "parent.rule = 'unverified';",
    "theory_claim": "parent.theory_equivalence_claim = true;",
    "child_anchor": "child.end_index -= 1;",
    "child_price": "child.end_value += .1;",
    "witness_anchor": "reverse.start_index += 1;",
    "witness_price": "reverse.start_value += .1;",
    "dependency_time": "child.current_placement.known_index = total - 1;",
    "frontier_representative": "parent.represented_by_id = null;",
    "descendant_representative": "child.represented_by_id = reverse.id;",
    "hidden_deferred": "d.deferred_ids = []; child.represented_by_id = null;",
    "invented_enclosing": "child.current_placement.enclosing_domain_ids = [d.domains[0].id];",
    "missing_conflict": (
        "const r = rows.find(r => r.current_placement.conflicts.length);"
        " r.current_placement.conflicts = [];"
    ),
    "forgotten_dependency": (
        "const r = rows.find(r => r.required_domain_ids.length); r.required_domain_ids = [];"
    ),
    "domain_source_ids": "d.domains[0].source_unit_ids.pop();",
    "domain_admissions": "d.domains[0].member_admissions.pop();",
    "domain_context_future": "d.domains[0].context_known_index = total;",
    "domain_unknown_claim": "d.domains[0].claim_kinds = ['guess'];",
    "cover_anchor": "d.source_cover[0].start_index += 1;",
    "forgotten_release": "d.domains[0].released_by_id = null; d.domains[0].status = 'retained';",
    "unresolved_anchor": "d.source_cover.at(-1).start_index += 1;",
}


@pytest.mark.parametrize("mutation", MUTATIONS)
@pytest.mark.parametrize("mirror", [False, True])
def test_inconsistent_release_graph_has_no_review_or_replay(mutation, mirror):
    data = release_fixture(mirror, 37)
    snapshot = released_movement_snapshot(*data)
    script = (
        """
import assert from 'node:assert/strict';
import { releaseEvidence } from './web-ui/src/released-evidence.ts';
let text = ''; for await (const chunk of process.stdin) text += chunk;
const { d, total } = JSON.parse(text);
assert.ok(releaseEvidence(d, total), 'Actual graph must pass before damage');
const rows = d.levels.flatMap(l => l.types);
const parent = d.levels.at(-1).types[0];
const child = rows.find(r => r.id === parent.child_ids[0]);
const reverse = rows.find(r => r.id === parent.opposite_id);
"""
        + MUTATIONS[mutation]
        + """
assert.ok(releaseEvidence(d, total) === undefined, 'Damaged graph was accepted');
"""
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2],
        input=json.dumps({"d": snapshot, "total": len(data[1])}),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("case", ["release", "partial", "internal", "remote_witness"])
def test_actual_historical_graphs_and_pending_owners_remain_readable(case, mirror):
    from tests.unit.test_chanlun_nested_ownership import triple_fixture

    data = (
        triple_fixture(mirror)
        if case == "internal"
        else lift_fixture(lift_fixture(release_fixture(mirror)))
        if case == "remote_witness"
        else release_fixture(
            mirror, 37, **({"middle": 61, "reverse": 150} if case == "partial" else {})
        )
    )
    items, bars, macd = data
    full = released_movement_snapshot(*data)
    last = full["levels"][-1]["types"][0]["known_index"]
    cuts = sorted({0, 1, 100, len(bars) // 2, last, last + 1, len(bars)})
    snapshots = [
        {"d": released_movement_snapshot(items, bars[:count], macd), "total": count}
        for count in cuts
    ]
    script = """
import assert from 'node:assert/strict';
import { releaseEvidence } from './web-ui/src/released-evidence.ts';
let text = ''; for await (const chunk of process.stdin) text += chunk;
const snapshots = JSON.parse(text);
const saved = structuredClone(snapshots);
for (const {d, total} of snapshots) {
  assert.ok(releaseEvidence(d, total), `Actual prefix ${total} was rejected`);
}
assert.deepEqual(snapshots, saved, 'Validation must not mutate snapshots');
"""
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=Path(__file__).resolve().parents[2],
        input=json.dumps(snapshots),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
