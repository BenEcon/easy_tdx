import test from 'node:test'
import assert from 'node:assert/strict'
import { expansionFocus } from '../src/expansion-focus.ts'
import { ChartViewportMemory } from '../src/chart-viewport.ts'

const sample = () => ({
  id: 'expansion:17:21', status: 'partition_found_awaiting_type_completion', known_index: 40,
  source_segment_indices: Array.from({length: 9}, (_, i) => i + 17),
  parts: [0, 1, 2].map(i => ({
    source_segment_indices: [17 + i * 3, 18 + i * 3, 19 + i * 3],
    start_index: 5 + i * 10, end_index: 15 + i * 10, known_index: 20 + i * 10,
  })),
})

test('locates the three raw ranges without relabelling them as MACD or confirmed centres', () => {
  const candidate = sample(), original = structuredClone(candidate)
  const focus = expansionFocus(candidate, 41, '候选核验')
  assert.equal(focus.scope, 'expansion')
  assert.equal(focus.title, '候选核验')
  assert.deepEqual(focus.ranges, [{label: 'A', start: 5, end: 15},
    {label: 'B', start: 15, end: 25}, {label: 'C', start: 25, end: 35}])
  assert.deepEqual(focus.points, [])
  assert.equal(focus.start, 2)
  assert.equal(focus.end, 38)
  assert.deepEqual(candidate, original)
})

test('candidate must already be observable at the CURRENT replay prefix', () => {
  assert.equal(expansionFocus(sample(), 40, ''), null)
  assert.ok(expansionFocus(sample(), 41, ''))
  for (const value of [null, undefined, NaN, -1, 40.5, false]) {
    assert.equal(expansionFocus({...sample(), known_index: value}, 50, ''), null)
  }
  for (const count of [0, -1, 40.5, NaN, Infinity]) assert.equal(expansionFocus(sample(), count, ''), null)
})

test('no incomplete, waiting or unsupported candidate is given a fabricated range', () => {
  for (const status of ['awaiting_centre_exit', 'requires_higher_level_inputs',
    'no_three_range_partition', 'unknown']) assert.equal(expansionFocus({...sample(), status}, 50, ''), null)
  for (const size of [0, 1, 2, 4]) {
    const candidate = sample()
    candidate.parts = Array.from({length: size}, () => candidate.parts[0])
    assert.equal(expansionFocus(candidate, 50, ''), null)
  }
})

test('raw bar boundaries must be contiguous and inside the visible window', () => {
  for (const patch of [{start_index: 14}, {start_index: 16}, {start_index: NaN},
    {start_index: -1}, {end_index: 15}, {end_index: 99}, {start_index: undefined},
    {known_index: 24}, {known_index: 41}]) {
    const candidate = sample()
    Object.assign(candidate.parts[1], patch)
    assert.equal(expansionFocus(candidate, 50, ''), null)
  }
})

test('source partitions must cover every original segment once, preserving nonzero IDs', () => {
  const mutations = [
    c => c.parts[1].source_segment_indices.reverse(),
    c => c.parts[1].source_segment_indices.pop(),
    c => c.parts[1].source_segment_indices[0] = c.parts[0].source_segment_indices[2],
    c => c.source_segment_indices[0] = -1,
    c => c.source_segment_indices[1] += 1,
    c => c.source_segment_indices = [],
  ]
  for (const mutate of mutations) {
    const candidate = sample()
    mutate(candidate)
    assert.equal(expansionFocus(candidate, 50, ''), null)
  }
})

test('conflicting geometric fallback remains viewable for manual audit', () => {
  assert.ok(expansionFocus({...sample(), partition_selection: 'geometric_fallback_with_conflicts'}, 50, ''))
  assert.ok(expansionFocus({...sample(), partition_selection: 'endpoint_consistent_preferred'}, 50, ''))
})

test('clearing a regrouping focus restores original zoom; a new replay snapshot does not', () => {
  const memory = new ChartViewportMemory(), scope = {}, before = {start: 30, end: 70}
  memory.update(scope, null, null)
  const focus = expansionFocus(sample(), 50, '')
  assert.equal(memory.update(scope, focus, before), null)
  assert.deepEqual(memory.update(scope, focus, {start: 20, end: 60}), {start: 20, end: 60})
  assert.deepEqual(memory.update(scope, null, {start: 20, end: 60}), before)
  memory.update(scope, focus, before)
  assert.equal(memory.update({}, null, {start: 20, end: 60}), null)
})
