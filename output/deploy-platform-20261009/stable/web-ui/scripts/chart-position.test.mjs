import test from 'node:test'
import assert from 'node:assert/strict'
import { chartBarIndex, priceAxisPadding } from '../src/chart-position.ts'

const bars = [{datetime:'2026-07-20T09:30:00'}, {datetime:'2026-07-20T09:31:00'},
  {datetime:'2026-07-21T09:30:00'}]
test('raw index overrides rounded dates, including zero', () => {
  assert.equal(chartBarIndex(bars, '2026-07-20', 1), 1)
  assert.equal(chartBarIndex(bars, null, 0), 0)
  for (const index of [-1, 3, NaN, 1.5, Infinity]) assert.equal(chartBarIndex(bars, '2026-07-21', index), null)
})
test('legacy intraday dates never fall back to the first bar of the day', () => {
  assert.equal(chartBarIndex(bars, '2026-07-20 09:31'), 1)
  assert.equal(chartBarIndex(bars, '2026-07-20 10:00'), null)
  assert.equal(chartBarIndex(bars, '2026-07-20'), null)
  assert.equal(chartBarIndex(bars, '2026-07-21'), 2)
})
test('duplicate formatted times fail safely without a raw index', () => {
  const duplicate = [...bars, {datetime:'2026-07-20T09:31:30'}]
  assert.equal(chartBarIndex(duplicate, '2026-07-20 09:31'), null)
  assert.equal(chartBarIndex(duplicate, '2026-07-20 09:31', 3), 3)
  assert.equal(chartBarIndex([], '2026-07-20'), null)
})
test('padding keeps the 23px marker plus radius inside the price pane', () => {
  for (const extent of [{min:19.21,max:27}, {min:1,max:1.01}, {min:0,max:1000}]) {
    const pad = priceAxisPadding(extent)
    const pixels = 342 * pad / (extent.max - extent.min + 2 * pad)
    assert.ok(pixels > 29)
  }
})
test('flat, zero and negative ranges get finite padding; invalid extents do not', () => {
  for (const extent of [{min:10,max:10}, {min:0,max:0}, {min:-5,max:-1}]) {
    assert.ok(Number.isFinite(priceAxisPadding(extent)) && priceAxisPadding(extent) > 0)
  }
  assert.equal(priceAxisPadding({min:NaN,max:1}), 0)
  assert.equal(priceAxisPadding({min:2,max:1}), 0)
})
