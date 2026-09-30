"""The real rejected API record must reach the browser's review helper."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from tests.unit.test_chanlun_engineering_movements import CONSOLIDATION
from tests.unit.test_chanlun_owner_witness import install_base_claims
from tests.unit.test_chanlun_signal_levels import fixture

NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='Node is needed for frontend integration')
VERIFY = """
import assert from 'node:assert/strict';
import { blockedOwnershipEvidence, blockedOwnershipConflict }
  from './web-ui/src/blocked-ownership-evidence.ts';
let text = ''; for await (const chunk of process.stdin) text += chunk;
const data = JSON.parse(text);
const entries = data.versions.flatMap(owner => (owner.blocked_ownership_candidates ?? [])
  .map(candidate => ({ owner, candidate })));
assert.equal(entries.length, 1);
const { owner, candidate } = entries[0];
const evidence = blockedOwnershipEvidence(owner, candidate, 140);
assert.deepEqual(evidence, { sources: [0,1,2,3,4], inputLevel: 0,
  reason: '反向确认结构属于其他归属区', original: 125, asOf: 135 });
assert.ok(candidate.original_known_date);
assert.ok(owner.known_date);
const detail = blockedOwnershipConflict(owner, candidate, 140);
assert.deepEqual(detail.source_domains, [[0,1,2,3,4]]);
assert.equal(detail.opposite.unit_id, 'segment:5');
assert.deepEqual(detail.opposite.owner_source_segment_indices, [5,6,7]);
assert.ok(detail.opposite.known_date);
assert.equal(blockedOwnershipEvidence(owner, candidate, 135), undefined);
candidate.source_unit_ids[0] = 'segment:999';
assert.equal(blockedOwnershipEvidence(owner, candidate, 140), undefined);
"""


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('history', ['full', 'summary'])
def test_real_foreign_witness_review_uses_version_time_not_original_completion(
        monkeypatch, mirror, history):
    items, bars, macd = fixture(CONSOLIDATION + [22, 27, 21], 0, 4, mirror)
    # Controlled ownership schedule; local geometry and MACD remain real.
    install_base_claims(monkeypatch, items)
    data = ChanlunResult(xds=items, klines=bars[:140], macd=macd).to_dict(
        ownership_history=history)['recursive_movement_ownership']
    # Full history also contains earlier valid records. Review only current owners.
    data['versions'] = [owner for owner in data['versions']
                        if owner['id'] in data['current_owner_ids']]
    checked = subprocess.run([NODE, '--input-type=module', '-e', VERIFY],
                             cwd=Path(__file__).resolve().parents[2], input=json.dumps(data),
                             text=True, capture_output=True, timeout=30, check=False)
    assert checked.returncode == 0, checked.stderr
    merged = ChanlunResult(xds=items, klines=bars[:141], macd=macd).to_dict(
        ownership_history='summary')['recursive_movement_ownership']
    assert all(not owner['blocked_ownership_candidates'] for owner in merged['versions'])
