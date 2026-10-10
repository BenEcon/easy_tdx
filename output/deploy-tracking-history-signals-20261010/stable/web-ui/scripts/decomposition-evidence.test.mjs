import test from 'node:test'
import assert from 'node:assert/strict'
import { decompositionCoverage, decompositionRange, decompositionRole } from '../src/decomposition-evidence.ts'

test('roles are Chinese and unknown roles never claim completion', () => {
  assert.equal(decompositionRole('pending_departure'), '离开待回试')
  assert.equal(decompositionRole('connector'), '中枢间连接段')
  assert.equal(decompositionRole('future'), '未知归属')
})
test('source ranges keep one-based indices without disguising gaps', () => {
  assert.equal(decompositionRange([0, 1, 2]), '线段 1–3')
  assert.equal(decompositionRange([4]), '线段 5')
  assert.equal(decompositionRange([0, 2]), '线段 1、3')
  assert.equal(decompositionRange([]), '无来源线段')
})
const fixture = () => ({input_segment_count: 3, accepted_segment_count: 3,
  rejected_suffix_count: 0, blocks: [{segment_indices: [0, 1]}, {segment_indices: [2]}]})
test('coverage checks counts, repeats and missing IDs', () => {
  assert.match(decompositionCoverage(fixture()), /无重复、无遗漏/)
  for (const ids of [[1], [3], [], [-1], [1.5]]) {
    const data = fixture()
    data.blocks[1].segment_indices = ids
    assert.match(decompositionCoverage(data), /不一致/)
  }
})
test('missing, empty and rejected suffix are explicit', () => {
  assert.match(decompositionCoverage(), /未提供/)
  assert.equal(decompositionCoverage({input_segment_count: 0, accepted_segment_count: 0,
    rejected_suffix_count: 0, blocks: []}), '暂无已确认线段')
  assert.match(decompositionCoverage({...fixture(), input_segment_count: 5,
    rejected_suffix_count: 2}), /后续 2 条未纳入/)
})
test('invalid counts and empty blocks cannot pass the coverage audit', () => {
  assert.match(decompositionCoverage({...fixture(), input_segment_count: NaN}), /不一致/)
  assert.match(decompositionCoverage({input_segment_count: -1, accepted_segment_count: 0,
    rejected_suffix_count: -1, blocks: []}), /不一致/)
  assert.match(decompositionCoverage({...fixture(), blocks: [
    {segment_indices: [0, 1, 2]}, {segment_indices: []}]}), /不一致/)
})
