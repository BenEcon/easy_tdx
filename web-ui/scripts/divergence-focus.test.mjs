import test from 'node:test'
import assert from 'node:assert/strict'
import { divergenceFocus } from '../src/divergence-focus.ts'

const item = () => ({bc: true, status: 'confirmed', evidence: {
  a_start: 5, a_end: 10, b_start: 10, b_end: 15, c_start: 15, c_end: 20,
}})
test('uses raw indices, allows shared endpoints and bounds zoom padding', () => {
  const focus = divergenceFocus(item(), 22, 'test')
  assert.deepEqual(focus.ranges, [{label: 'A', start: 5, end: 10},
    {label: 'B', start: 10, end: 15}, {label: 'C', start: 15, end: 20}])
  assert.equal(focus.start, 2)
  assert.equal(focus.end, 21)
})
test('does not invent a B interval or infer indices from formatted dates', () => {
  const value = item()
  delete value.evidence.b_start
  delete value.evidence.b_end
  assert.equal(divergenceFocus(value, 22, '').ranges.length, 2)
  assert.equal(divergenceFocus({bc: true, intervals: {a_start: '2026-01-01'}}, 22, ''), null)
})
test('rejects partial, reversed, overlapping and out-of-snapshot evidence', () => {
  for (const change of [{a_start: -1}, {a_start: 1.5}, {a_end: 4}, {c_end: 22},
    {b_start: 9}, {c_start: 14}, {c_end: NaN}, {b_end: undefined}]) {
    const value = item()
    Object.assign(value.evidence, change)
    assert.equal(divergenceFocus(value, 22, ''), null)
  }
})
test('does not present superseded or false events; candidates remain candidates', () => {
  assert.equal(divergenceFocus({...item(), status: 'superseded'}, 22, ''), null)
  assert.equal(divergenceFocus({...item(), bc: false}, 22, ''), null)
  assert.ok(divergenceFocus({...item(), status: 'candidate'}, 22, '候选'))
  assert.equal(divergenceFocus(item(), 0, ''), null)
})

test('dual-line divergence uses two exact raw indices, never artificial ABC ranges', () => {
  const value = {...item(), type: 'macd', reference_index: 5, signal_index: 18}
  const focus = divergenceFocus(value, 22, '双线背离')
  assert.equal(focus.mode, 'points')
  assert.deepEqual(focus.ranges, [])
  assert.deepEqual(focus.points, [{label: '前极值', index: 5}, {label: '本次极值', index: 18}])
  assert.equal(focus.start, 2)
  assert.equal(focus.end, 21)
})

test('dual-line focus rejects missing, duplicate, reversed and out-of-range points', () => {
  for (const [previous, current] of [[null, 12], [5, undefined], [5, 5], [6, 5], [-1, 5],
    [1.5, 6], [5, NaN], [5, 22], [false, 5]]) {
    assert.equal(divergenceFocus({...item(), type: 'macd', reference_index: previous,
      signal_index: current, curr_date: '2026-01-01'}, 22, ''), null)
  }
})
