import test from 'node:test'
import assert from 'node:assert/strict'
import { blockedOwnershipConflict as resolve } from '../src/blocked-ownership-evidence.ts'

function fixture() {
  const owner = { known_index: 20, source_segment_indices: [0,1,2,3,4,5],
    levels: [{ level: 1, types: ['a','b','w'].map((id,i) => ({ id, level: 1, known_index: 10,
      source_segment_indices: [2*i,2*i+1], current_owner_id: ['left','right','witness'][i] })) }],
    nested_owners: ['left','right','witness'].map((id,i) => ({ id, input_level: 1,
      source_segment_indices: [2*i,2*i+1] })) }
  const candidate = { source_unit_ids: ['a','b'], original_known_index: 15,
    reason: 'crosses_current_ownership_boundary', ownership_conflict: {
      input_level: 1, source_segment_indices: [0,1,2,3], source_domains: [[0,1],[2,3]],
      opposite: { unit_id: 'w', source_segment_indices: [4,5], known_index: 10,
        owner_source_segment_indices: [4,5] },
    } }
  return { owner, candidate }
}

test('cross-boundary details resolve actual input and nested ownership records', () => {
  const { owner, candidate } = fixture(), before = structuredClone({ owner, candidate })
  assert.deepEqual(resolve(owner, candidate, 21), candidate.ownership_conflict)
  assert.deepEqual({ owner, candidate }, before)
})
test('unowned reverse evidence stays explicitly unowned for boundary rejection', () => {
  const { owner, candidate } = fixture()
  owner.levels[0].types[2].current_owner_id = 'root'
  owner.nested_owners.pop()
  candidate.ownership_conflict.opposite.owner_source_segment_indices = null
  assert.deepEqual(resolve(owner, candidate, 21), candidate.ownership_conflict)
})
test('foreign witness can be shown for an otherwise single-owner candidate', () => {
  const { owner, candidate } = fixture()
  owner.nested_owners.splice(0, 2, { id: 'combined', input_level: 1, source_segment_indices: [0,1,2,3] })
  candidate.ownership_conflict.source_domains = [[0,1,2,3]]
  candidate.reason = 'opposite_witness_owned_by_another_domain'
  assert.deepEqual(resolve(owner, candidate, 21), candidate.ownership_conflict)
})
test('legacy candidates do not invent missing conflict details', () => {
  const { owner, candidate } = fixture(); delete candidate.ownership_conflict
  assert.equal(resolve(owner, candidate, 21), undefined)
})
for (const [name, damage] of [
  ['mismatched candidate sources', (o,d) => { d.source_segment_indices = [0,1,2] }],
  ['wrong layer', (o,d) => { d.input_level = 2 }],
  ['unknown reverse input', (o,d) => { d.opposite.unit_id = 'missing' }],
  ['wrong reverse range', (o,d) => { d.opposite.source_segment_indices = [5] }],
  ['reverse overlaps prices', (o,d) => { d.opposite.source_segment_indices = [3,4] }],
  ['future reverse confirmation', (o,d) => { d.opposite.known_index = 16 }],
  ['wrong reverse time', (o,d) => { d.opposite.known_index = 9 }],
  ['incomplete domain list', (o,d) => { d.source_domains.pop() }],
  ['duplicate domains', (o,d) => { d.source_domains.push([2,3]) }],
  ['noncontinuous domain', (o,d) => { d.source_domains[0] = [0,2] }],
  ['foreign domain misses witness', (o,d) => { d.opposite.owner_source_segment_indices = [0,1] }],
  ['false unowned witness', (o,d) => { d.opposite.owner_source_segment_indices = null }],
  ['missing nested record', o => { o.nested_owners.pop() }],
  ['wrong reason', (o,d,c) => { c.reason = 'opposite_witness_owned_by_another_domain' }],
]) test(`damaged detail is not presented: ${name}`, () => {
  const { owner, candidate } = fixture(); damage(owner, candidate.ownership_conflict, candidate)
  assert.equal(resolve(owner, candidate, 21), undefined)
})
