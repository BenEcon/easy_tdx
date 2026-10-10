"""Real release graphs pass the browser guard; damaged graphs never get replay."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.released_recursion import released_movement_snapshot
from tests.unit.test_chanlun_released_recursion import lift_fixture, release_fixture

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is needed for frontend integration")
VERIFY = """
import assert from 'node:assert/strict';
import { releaseEvidence } from './web-ui/src/released-evidence.ts';
let text = ''; for await (const chunk of process.stdin) text += chunk;
const { data, total } = JSON.parse(text);
const evidence = releaseEvidence(data, total);
assert.ok(evidence, 'Actual backend snapshot must pass');
assert.equal(evidence.frontier.length, data.frontier_ids.length);
const parent = data.levels.at(-1).types[0];
assert.ok(parent.eligible_for_external_recursion);
assert.ok(evidence.domains.size);
const mutations = [
  d => { d.rule = 'unknown'; },
  d => { d.eligible_for_trading = true; },
  d => { d.as_of_index = total; },
  d => { d.levels.at(-1).types[0].known_index = total; },
  d => { d.levels.at(-1).types[0].source_segment_indices.pop(); },
  d => { d.levels.at(-1).types[0].child_ids.reverse(); },
  d => { d.levels.at(-1).types[0].opposite_id = d.levels.at(-1).types[0].child_ids[0]; },
  d => { d.levels.at(-1).types[0].required_domain_ids = [d.domains[0].id]; },
  d => { d.levels.at(-1).types[0].current_placement.released_domain_ids = ['missing']; },
  d => { d.domains[0].required_parent_level = 99; },
  d => { d.domains[0].released_by_id = 'missing'; },
  d => { d.frontier_ids.push(d.frontier_ids[0]); },
  d => { d.source_cover[0].source_segment_indices.shift(); },
  d => { d.source_cover[0].status = 'unresolved'; },
  d => { d.unresolved_segment_indices.push(999999); },
  d => { d.levels[0].types[0].current_placement = null; },
  d => { d.levels = null; },
];
for (const mutate of mutations) {
  const broken = structuredClone(data); mutate(broken);
  assert.equal(releaseEvidence(broken, total), undefined, mutate.toString());
}
assert.equal(releaseEvidence(undefined, total), undefined);
"""


def verify(data, total):
    checked = subprocess.run(
        [NODE, "--input-type=module", "-e", VERIFY],
        cwd=Path(__file__).resolve().parents[2],
        input=json.dumps({"data": data, "total": total}),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("history", ["full", "summary"])
def test_dated_release_api_reaches_browser_in_both_history_modes(mirror, history):
    items, bars, macd = release_fixture(mirror, 37)
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    data = result.to_dict(ownership_history=history)["released_movement_recursion"]
    assert data["as_of_date"]
    assert data["levels"][-1]["types"][0]["current_placement"]["known_date"]
    verify(data, len(bars))
    saved = result.to_dict(ownership_history=history)["released_movement_recursion"]
    data["domains"][0]["source_segment_indices"].clear()
    assert result.to_dict(ownership_history=history)["released_movement_recursion"] == saved


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("depth", [1, 2])
def test_deep_release_engine_graph_reaches_browser(depth, mirror):
    data = release_fixture(mirror)
    for step in range(depth):
        data = lift_fixture(data, tail_step=10 if step == 0 and depth == 2 else 1)
    verify(released_movement_snapshot(*data), len(data[1]))
