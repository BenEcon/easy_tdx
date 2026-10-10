import test from 'node:test'
import assert from 'node:assert/strict'
import { provisionalCandle, provisionalColumn } from '../src/provisional-bars.ts'

test('forming candles preserve OHLC and use dashed empty outlines', () => {
  const prices = [10, 11, 9, 12]
  assert.equal(provisionalCandle(prices, true), prices)
  assert.equal(provisionalCandle(prices, undefined), prices)
  const pending = provisionalCandle(prices, false)
  assert.equal(pending.value, prices)
  assert.equal(pending.itemStyle.borderType, 'dashed')
  assert.equal(pending.itemStyle.color, 'transparent')
  assert.equal(pending.itemStyle.color0, 'transparent')
})

test('forming volume and signed MACD columns preserve values and direction', () => {
  for (const value of [0, 100, -.00004]) {
    assert.equal(provisionalColumn(value, true, value >= 0), value)
    const pending = provisionalColumn(value, false, value >= 0)
    assert.equal(pending.value, value)
    assert.equal(pending.itemStyle.borderType, 'dashed')
    assert.equal(pending.itemStyle.color, 'transparent')
  }
})
