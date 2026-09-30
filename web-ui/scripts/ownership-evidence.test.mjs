import test from 'node:test'
import assert from 'node:assert/strict'
import { currentOwners, internalSource, internalStatus, ownerLabel } from '../src/ownership-evidence.ts'

test('only current owner revisions form the displayed ownership set', () => {
  const old = { id: 'old' }, now = { id: 'now' }
  assert.deepEqual(currentOwners(), [])
  assert.deepEqual(currentOwners({ versions: [old, now], current_owner_ids: ['now'] }), [now])
})
test('internal provenance remains distinct and validates enclosing ownership', () => {
  assert.equal(internalSource('owner:0:47:at:335/movement:consolidation:L2:5:37'), '内部 M2 盘整（线段 6–38）')
  assert.equal(internalSource('segment:15'), '线段 16')
  for (const id of ['owner:6:47:at:335/movement:trend:L2:5:37',
    'owner:0:36:at:335/movement:trend:L2:5:37', 'owner:0:47:at:335/movement:trend:L2:37:5']) {
    assert.equal(internalSource(id), '未知来源')
  }
})
test('parent-covered history is not labeled as an additional effective input', () => {
  const owner = { frontier_ids: ['parent', 'witness'] }
  assert.equal(internalStatus(owner, 'parent'), '当前内部输入')
  assert.equal(internalStatus(owner, 'child'), '已被父级包含')
})
test('nested provenance validates containment and strictly increasing input levels', () => {
  const root = 'owner:0:499:at:900'
  assert.equal(internalSource(`${root}/nested:M1:5:490:at:400/nested:M2:40:450:at:800/movement:trend:L3:55:400`), '内部 M3 趋势（线段 56–401）')
  for (const path of ['nested:M1:5:490:at:400/nested:M1:40:450:at:800',
    'nested:M2:40:450:at:800/nested:M1:40:450:at:800',
    'nested:M1:5:490:at:400/nested:M2:0:450:at:800', 'nested:M3:40:450:at:800']) {
    assert.equal(internalSource(`${root}/${path}/movement:trend:L3:55:400`), '未知来源')
  }
})
test('current owner labels are distinct from creation IDs and tolerate old snapshots', () => {
  const owner = { id: 'root', nested_owners: [{ id: 'nested', input_level: 2, source_segment_indices: [37,38,39] }] }
  assert.equal(ownerLabel(owner, 'root'), '基础归属区')
  assert.equal(ownerLabel(owner, 'nested'), 'M2 输入层 · 线段 38–40')
  assert.equal(ownerLabel(owner, 'unknown'), '归属待核验')
  assert.equal(ownerLabel({ id: 'root' }), '基础归属区')
})
