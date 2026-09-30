import test from 'node:test'
import assert from 'node:assert/strict'
import { engineeringSource, engineeringValue, recursiveRelation, admissionReason } from '../src/engineering-trend-evidence.ts'

test('engineering provenance uses the same one-based numbering as other inspectors', () => {
  assert.equal(engineeringSource('segment:0'), '线段 1')
  assert.equal(engineeringSource('trend:L2:37:117'), 'T2 趋势（线段 38–118）')
})
test('mixed recursion distinguishes consolidation and trend from the old trend view', () => {
  assert.equal(engineeringSource('movement:consolidation:L2:37:117'), 'M2 盘整（线段 38–118）')
  assert.equal(engineeringSource('movement:trend:L1:0:8'), 'M1 趋势（线段 1–9）')
  for (const id of ['movement:trend:L0:0:8', 'movement:consolidation:L1:8:0', 'movement:unknown:L1:0:8']) {
    assert.equal(engineeringSource(id), '未知来源')
  }
})
test('unknown or reversed provenance is not presented as a completed trend', () => {
  for (const id of ['trend:L0:0:8', 'trend:L1:8:0', 'segment:-1', '', 'future']) {
    assert.equal(engineeringSource(id), '未知来源')
  }
})
test('indicator and price values use two decimals without inventing missing evidence', () => {
  assert.equal(engineeringValue(.12345), '0.12')
  assert.equal(engineeringValue(-1.234), '-1.23')
  assert.equal(engineeringValue(0), '0.00')
  for (const value of [undefined, NaN, Infinity]) assert.equal(engineeringValue(value), '—')
})
test('recursive centre relations never call extension candidates completed types', () => {
  assert.equal(recursiveRelation('initial'), '本连续链首个中枢')
  assert.equal(recursiveRelation('expansion_candidate'), '外围相交，扩展待判定')
  assert.equal(recursiveRelation('unknown'), '关系未提供')
})
test('admissions distinguish unit confirmation from later failed-return admission', () => {
  assert.equal(admissionReason('seed_formation'), '初始三单元形成')
  assert.equal(admissionReason('failed_departure_return'), '回试失败后纳入')
  assert.equal(admissionReason('extension'), '中枢延伸接纳')
  assert.equal(admissionReason('future'), '接纳方式未提供')
})
