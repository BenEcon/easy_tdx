"""Price/MACD drilldown must resolve current backend evidence, not stale UI objects."""

import json
import subprocess
from pathlib import Path

import pytest

from easy_tdx.chanlun.released_recursion import released_movement_snapshot
from tests.unit.test_chanlun_released_frontend import NODE
from tests.unit.test_chanlun_released_recursion import lift_fixture, release_fixture

VERIFY = """
import assert from 'node:assert/strict';
import { releasedFocus } from './web-ui/src/released-focus.ts';
import { releaseBlockers } from './web-ui/src/release-review.ts';
let text = ''; for await (const chunk of process.stdin) text += chunk;
const { data, total } = JSON.parse(text), before = JSON.stringify(data);
for (const layer of data.levels) for (const record of layer.types) {
  for (const blocker of releaseBlockers(data, record.id, total)) {
    const domain = data.domains.find(d => d.id === blocker.domainId);
    const missing = domain.source_segment_indices.filter(s =>
      !record.source_segment_indices.includes(s));
    assert.deepEqual(blocker.missingSources, missing);
    assert.equal(blocker.path[0].id, record.id);
    for (let i = 1; i < blocker.path.length; i++) {
      assert.equal(blocker.path[i].level, blocker.path[i - 1].level - 1);
    }
  }
  for (const mode of ['movement', 'macd', 'reverse']) {
    const focus = releasedFocus(data, record.id, total, mode);
    assert.ok(focus, `${record.id} ${mode}`);
    assert.equal(focus.scope, 'released');
    assert.ok(focus.start >= 0 && focus.end < total);
    if (mode === 'movement') assert.equal(focus.ranges[0].end, record.end_index);
    if (mode === 'reverse') assert.equal(focus.ranges[0].start, record.end_index);
    for (const r of focus.ranges) assert.ok(r.end <= record.known_index);
  }
}
assert.equal(JSON.stringify(data), before);
const parent = data.levels.at(-1).types[0];
assert.equal(releasedFocus(data, 'stale-record', total, 'movement'), null);
assert.equal(releasedFocus(undefined, parent.id, total, 'movement'), null);
assert.equal(releasedFocus(data, parent.id, 0, 'movement'), null);
for (const patch of [{a_start: -1}, {c_end: total}, {a_end: parent.end_index},
  {a_start: null}, {c_start: NaN}, {a_start: .5}]) {
  const broken = structuredClone(data);
  Object.assign(broken.levels.at(-1).types[0].macd_evidence, patch);
  assert.equal(releasedFocus(broken, parent.id, total, 'macd'), null);
}
const broken = structuredClone(data);
broken.levels.at(-1).types[0].child_ids.reverse();
assert.equal(releasedFocus(broken, parent.id, total, 'movement'), null);
"""


@pytest.mark.skipif(NODE is None, reason="Node required for TypeScript integration")
@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("depth", [0, 1, 2])
def test_actual_parent_child_focus(depth, mirror):
    fixture = release_fixture(mirror)
    for step in range(depth):
        fixture = lift_fixture(fixture, tail_step=10 if depth == 2 and step == 0 else 1)
    data = released_movement_snapshot(*fixture)
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", VERIFY],
        cwd=Path(__file__).resolve().parents[2],
        input=json.dumps({"data": data, "total": len(fixture[1])}),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
