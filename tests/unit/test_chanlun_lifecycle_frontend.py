"""Real recursive output must survive the browser's evidence validator.

Node reads the actual TypeScript helper and receives snapshots over stdin;
no hand-copied JSON fixture or temporary web entry point is used.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.structure import confirmed_segment_prefix
from tests.unit.test_chanlun_deep_dependencies import fourth_fixture
from tests.unit.test_chanlun_nested_ownership import (
    final_internal_snapshot,
    nested_fixture,
    triple_fixture,
)

NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='Node is needed for frontend integration')
ROOT = Path(__file__).resolve().parents[2]
VERIFY = """
import assert from 'node:assert/strict';
import { ownershipLifecycle } from './web-ui/src/ownership-evidence.ts';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const { owners, total } = JSON.parse(input);
let checked = 0;
for (const owner of owners) for (const domain of owner.nested_owners ?? []) {
  assert.deepEqual(ownershipLifecycle(domain, total, owner), domain.lifecycle_events, domain.id);
  checked++;
  const broken = structuredClone(domain);
  broken.lifecycle_events[0].last_source_segment_index++;
  assert.equal(ownershipLifecycle(broken, total, owner), undefined);
}
assert.ok(checked > 0);
process.stdout.write(String(checked));
"""


def check_browser_evidence(owners, total):
    checked = subprocess.run(
        [NODE, '--input-type=module', '-e', VERIFY], cwd=ROOT,
        input=json.dumps({'owners': owners, 'total': total}, allow_nan=False),
        text=True, capture_output=True, timeout=30, check=False,
    )
    assert checked.returncode == 0, checked.stderr
    return int(checked.stdout)


@pytest.mark.parametrize('mirror', [False, True])
@pytest.mark.parametrize('depth', [2, 3, 4])
def test_real_multi_level_history_validates_without_using_later_placement_time(depth, mirror):
    items, bars, macd = {2: nested_fixture, 3: triple_fixture, 4: fourth_fixture}[depth](mirror)
    available = confirmed_segment_prefix(items, len(bars))
    result = final_internal_snapshot(items, bars, macd)
    owner = {**result, 'id': (f'owner:{available[0].index}:{available[-1].index}'
                             f':at:{available[-1].confirmed_index}'),
             'source_segment_indices': [item.index for item in available]}
    assert check_browser_evidence([owner], len(bars)) == depth - 1


@pytest.mark.parametrize('history', ['full', 'summary'])
@pytest.mark.parametrize('count', [401, 531])
def test_dated_api_history_and_confirmation_prefix_validate(history, count):
    items, bars, macd = nested_fixture(offset=37)
    result = ChanlunResult(xds=items, klines=bars[:count], macd=macd)
    data = result.to_dict(ownership_history=history)['recursive_movement_ownership']
    assert check_browser_evidence(data['versions'], count) >= 1
