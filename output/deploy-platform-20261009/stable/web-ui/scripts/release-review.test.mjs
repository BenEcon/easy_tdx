import test from 'node:test'
import assert from 'node:assert/strict'
import { validHistoryBatch, historyStateLabel } from '../src/release-review.ts'

const sample = () => ({scope: 'raw_prefix_release_history_v1', start_count: 1, end_count: 40,
  historical_data_vintage: false, eligible_for_trading: false,
  events: [{id: 'x', index: 39, date: '2026-01-01', change: 'added', before: null,
    after: {kind: 'domain', source_segment_indices: [3, 4, 5], status: 'retained'}}]})
test('accepts bounded history and empty verified batches', () => {
  assert.ok(validHistoryBatch(sample(), 1, 40))
  assert.ok(validHistoryBatch({...sample(), events: []}, 1, 40))
})
test('rejects wrong batch, future indices, broken sources and contradictory state', () => {
  const changes = [b => b.start_count++, b => b.end_count++, b => b.eligible_for_trading = true,
    b => b.events[0].index = 40, b => b.events[0].index = -1, b => b.events[0].index = 1.5,
    b => b.events[0].after.source_segment_indices = [3, 5],
    b => b.events[0].change = 'unknown', b => b.events[0].after = null,
    b => b.events[0].change = 'removed', b => b.events = null,
    b => b.events[0].id = '', b => b.events[0].after.kind = 'invented']
  for (const change of changes) { const b = sample(); change(b); assert.equal(validHistoryBatch(b, 1, 40), false) }
})
test('research labels distinguish absence, release, retained and internal', () => {
  assert.equal(historyStateLabel(null), '本前缀中不存在')
  assert.equal(historyStateLabel(sample().events[0].after), '归属区约束保留')
  assert.equal(historyStateLabel({kind:'domain', status:'released_by_parent'}), '整区已由父走势覆盖释放')
  assert.equal(historyStateLabel({kind:'movement', eligible_for_external_recursion:true}), '外部可用')
  assert.equal(historyStateLabel({kind:'movement', represented_by_id:'parent'}), '由父走势代表／内部依据')
})
