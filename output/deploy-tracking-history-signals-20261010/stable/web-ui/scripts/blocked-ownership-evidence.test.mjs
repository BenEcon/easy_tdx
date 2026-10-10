import test from 'node:test'
import assert from 'node:assert/strict'
import { blockedOwnershipEvidence as evidence } from '../src/blocked-ownership-evidence.ts'

function fixture() {
  const owner = { known_index: 30, source_segment_indices: [37, 38, 39, 40, 41, 42],
    levels: [{ level: 1, types: [
      { id: 'first', level: 1, known_index: 12, source_segment_indices: [37, 38, 39] },
      { id: 'second', level: 1, known_index: 18, source_segment_indices: [40, 41, 42] },
    ] }] }
  const candidate = { reason: 'crosses_current_ownership_boundary',
    source_unit_ids: ['first', 'second'], original_known_index: 20 }
  return { owner, candidate }
}

test('higher sources resolve actual records and separate original from current review time', () => {
  const { owner, candidate } = fixture(), before = structuredClone({ owner, candidate })
  assert.deepEqual(evidence(owner, candidate, 31), { sources: [37, 38, 39, 40, 41, 42],
    inputLevel: 1, reason: '来源跨越当前归属边界', original: 20, asOf: 30 })
  assert.deepEqual({ owner, candidate }, before)
})

test('base sources and foreign witness rejection have distinct Chinese descriptions', () => {
  const { owner, candidate } = fixture()
  candidate.source_unit_ids = ['segment:37', 'segment:38']
  candidate.reason = 'opposite_witness_owned_by_another_domain'
  assert.deepEqual(evidence(owner, candidate, 31), { sources: [37, 38], inputLevel: 0,
    reason: '反向确认结构属于其他归属区', original: 20, asOf: 30 })
})

for (const [label, corrupt] of [
  ['unknown reason', (o, c) => { c.reason = 'new_unrecognized_reason' }],
  ['prototype key', (o, c) => { c.reason = 'constructor' }],
  ['future version', o => { o.known_index = 31 }],
  ['future completion', (o, c) => { c.original_known_index = 31 }],
  ['missing time', (o, c) => { delete c.original_known_index }],
  ['empty source', (o, c) => { c.source_unit_ids = [] }],
  ['duplicate source', (o, c) => { c.source_unit_ids = ['first', 'first'] }],
  ['unknown source', (o, c) => { c.source_unit_ids[0] = 'missing' }],
  ['mixed levels', (o, c) => { c.source_unit_ids[0] = 'segment:37' }],
  ['future child', o => { o.levels[0].types[0].known_index = 21 }],
  ['wrong child level', o => { o.levels[0].types[0].level = 2 }],
  ['duplicate record', o => { o.levels[0].types.push(o.levels[0].types[0]) }],
  ['empty record range', o => { o.levels[0].types[0].source_segment_indices = [] }],
  ['gap', o => { o.levels[0].types[0].source_segment_indices = [37, 39] }],
  ['wrong parent range', o => { o.source_segment_indices.shift() }],
  ['reversed sources', (o, c) => { c.source_unit_ids.reverse() }],
  ['unsafe base number', (o, c) => { c.source_unit_ids = ['segment:99999999999999999999'] }],
]) test(`inconsistent candidate has no replay evidence: ${label}`, () => {
  const { owner, candidate } = fixture(); corrupt(owner, candidate)
  assert.equal(evidence(owner, candidate, 31), undefined)
})
