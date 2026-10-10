import test from 'node:test'
import assert from 'node:assert/strict'
import { DEFAULT_LINE_WIDTHS, structureLineWidth, emphasizedLineWidth } from '../src/chanlun-line-width.ts'

test('structure widths retain existing defaults and hover appearance', () => {
  assert.deepEqual(DEFAULT_LINE_WIDTHS, { bi: 1.35, xd: 1.8 })
  assert.equal(structureLineWidth('bi'), 1.35)
  assert.equal(structureLineWidth('xd'), 1.8)
  assert.equal(emphasizedLineWidth('bi'), 2)
  assert.equal(emphasizedLineWidth('xd'), 2.6)
})

test('manual values stay finite, bounded, and at two decimal places', () => {
  for (const kind of ['bi', 'xd']) {
    for (const value of [NaN, Infinity, -Infinity, undefined]) {
      assert.equal(structureLineWidth(kind, value), DEFAULT_LINE_WIDTHS[kind])
    }
    assert.equal(structureLineWidth(kind, -1), 0.5)
    assert.equal(structureLineWidth(kind, 20), 6)
    assert.equal(structureLineWidth(kind, 2.345), 2.35)
    assert.equal(structureLineWidth(kind, 1.35 + 0.05), 1.4)
    for (const value of [0.5, 1.35, 1.8, 3, 6]) {
      assert.ok(emphasizedLineWidth(kind, value) > structureLineWidth(kind, value))
    }
  }
})
