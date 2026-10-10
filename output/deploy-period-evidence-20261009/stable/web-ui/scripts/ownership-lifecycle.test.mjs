import test from 'node:test'
import assert from 'node:assert/strict'
import { lifecycleLabel, ownershipLifecycle } from '../src/ownership-evidence.ts'

function sample() {
  const event = (id, known_index, kind, previous_owner_ids, first, last, count, added_unit_ids) => ({
    id, known_index, kind, previous_owner_ids, first_source_segment_index: first,
    last_source_segment_index: last, source_unit_count: count, added_unit_ids,
  })
  return { id: 'merged', parent_owner_id: 'root', input_level: 1, known_index: 15,
    source_segment_indices: [0, 1, 2, 3, 4, 5], source_unit_ids: ['a', 'b', 'c', 'd'],
    member_admissions: ['a', 'b', 'c', 'd'].map(unit_id => ({ unit_id, admitted_index: 15 })),
    lifecycle_events: [event('left', 10, 'formed', [], 0, 1, 1, ['a']),
      event('right', 10, 'formed', [], 4, 5, 1, ['d']),
      event('grown', 12, 'expanded', ['left'], 0, 3, 3, ['b', 'c']),
      event('merged', 15, 'merged', ['grown', 'right'], 0, 5, 4, [])] }
}

function context() {
  return { id: 'root', source_segment_indices: [0, 1, 2, 3, 4, 5], levels: [{ level: 1,
    types: [[0, 1], [2], [3], [4, 5]].map((source_segment_indices, i) => ({
      id: ['a', 'b', 'c', 'd'][i], source_segment_indices, level: 1,
      known_index: i === 1 || i === 2 ? 12 : 10,
      current_owner_id: 'merged', current_owner_known_index: 15,
    })) }], nested_owners: [sample()] }
}

const verify = (domain, total = 16, owner = context()) => ownershipLifecycle(domain, total, owner)

test('complete lifecycle stays chronological, does not mutate input, and uses Chinese labels', () => {
  const domain = sample(), before = structuredClone(domain)
  assert.deepEqual(verify(domain), domain.lifecycle_events)
  assert.deepEqual(domain, before)
  assert.deepEqual(['formed', 'expanded', 'merged', 'unknown'].map(lifecycleLabel),
    ['归属形成', '范围扩展', '归属合并', '待核验事件'])
})
test('legacy or future history is not invented', () => {
  assert.equal(verify({ ...sample(), lifecycle_events: undefined }), undefined)
  assert.equal(verify({ ...sample(), lifecycle_events: [] }), undefined)
  assert.equal(verify(sample(), 15), undefined)
})
test('dangling, reordered, duplicated, miscounted and conflicting histories fail closed', () => {
  for (const corrupt of [
    d => { d.lifecycle_events[3].previous_owner_ids[0] = 'missing' },
    d => { d.lifecycle_events[3].previous_owner_ids[0] = 'left' }, // Already replaced.
    d => { d.lifecycle_events[2].known_index = 9 },
    d => { d.lifecycle_events[1].id = 'left' },
    d => { d.lifecycle_events[2].added_unit_ids = ['a', 'c'] },
    d => { d.lifecycle_events[3].source_unit_count = 3 },
    d => { d.lifecycle_events[3].kind = 'formed' },
    d => { d.lifecycle_events[1].first_source_segment_index = 1 },
    d => { d.lifecycle_events[3].last_source_segment_index = 6 },
    d => { d.id = 'unknown' },
    d => { d.lifecycle_events[3].previous_owner_ids = ['grown', 'grown'] },
  ]) {
    const domain = sample(); corrupt(domain)
    assert.equal(verify(domain), undefined)
  }
})

test('equal counts cannot hide swapped source identities', () => {
  const domain = sample()
  domain.lifecycle_events[0].added_unit_ids = ['d']
  domain.lifecycle_events[1].added_unit_ids = ['a']
  assert.equal(verify(domain), undefined)
})

test('intermediate event boundaries must equal actual inherited and added sources', () => {
  const domain = sample()
  domain.lifecycle_events[0].last_source_segment_index = 2
  assert.equal(verify(domain), undefined)
})

test('input evidence must exist at the correct level and be available at admission', () => {
  for (const corrupt of [
    o => { o.levels[0].types.pop() },
    o => { o.levels[0].types.push(structuredClone(o.levels[0].types[0])) },
    o => { o.levels[0].types[0].level = 2 },
    o => { o.levels[0].level = 2 },
    o => { o.levels[0].types[0].known_index = 11 },
    o => { o.levels[0].types[0].known_index = NaN },
    o => { o.levels[0].types[0].source_segment_indices = [0, 2] },
    o => { o.levels[0].types[1].source_segment_indices = [1] },
    o => { o.levels[0].types[0].current_owner_id = 'foreign' },
  ]) {
    const owner = context(); corrupt(owner)
    assert.equal(verify(sample(), 16, owner), undefined)
  }
})

test('invalid domain sources, membership and parent context fail closed', () => {
  for (const corrupt of [
    d => { d.source_segment_indices = [] },
    d => { d.source_segment_indices = [0, 1, 3, 4, 5] },
    d => { d.source_segment_indices = [0, 1, 2, 2, 4, 5] },
    d => { d.source_unit_ids = ['a', 'c', 'b', 'd'] },
    d => { d.input_level = 2 },
    d => { d.parent_owner_id = 'missing' },
    d => { d.member_admissions.pop() },
    d => { d.member_admissions[0].admitted_index = 10 },
    d => { d.known_index = 16 },
  ]) {
    const domain = sample(); corrupt(domain)
    assert.equal(verify(domain), undefined)
  }
  assert.equal(ownershipLifecycle(sample(), 16), undefined)
})

test('leftward growth, shifted sources and newly filled merge gaps remain valid', () => {
  const domain = sample(), owner = context()
  domain.lifecycle_events[2].last_source_segment_index = 2
  domain.lifecycle_events[2].source_unit_count = 2
  domain.lifecycle_events[2].added_unit_ids = ['b']
  domain.lifecycle_events[3].added_unit_ids = ['c']
  assert.deepEqual(verify(domain, 16, owner), domain.lifecycle_events)
  // Reflect the price-source axis, then move it away from zero. The time axis
  // is unchanged; chronological events need not move left to right.
  const reflect = values => values.map(value => 42 - value).reverse()
  domain.source_segment_indices = reflect(domain.source_segment_indices)
  domain.source_unit_ids.reverse()
  owner.source_segment_indices = reflect(owner.source_segment_indices)
  for (const unit of owner.levels[0].types) unit.source_segment_indices = reflect(unit.source_segment_indices)
  for (const event of domain.lifecycle_events) {
    [event.first_source_segment_index, event.last_source_segment_index] =
      [42 - event.last_source_segment_index, 42 - event.first_source_segment_index]
  }
  assert.deepEqual(verify(domain, 16, owner), domain.lifecycle_events)
})
