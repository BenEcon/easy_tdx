import test from 'node:test'
import assert from 'node:assert/strict'
import { candleFill, candleTransparency, DEFAULT_CANDLE_TRANSPARENCY } from '../src/candle-fill.ts'
test('80 percent transparency is 20 percent alpha, for both candle directions',()=>{
  assert.equal(DEFAULT_CANDLE_TRANSPARENCY,80)
  assert.equal(candleFill('#ff5e68'),'rgba(255,94,104,0.2)')
  assert.equal(candleFill('#30d17b'),'rgba(48,209,123,0.2)')
  assert.equal(candleFill('#ff5e68',0),'rgba(255,94,104,1)')
  assert.equal(candleFill('#ff5e68',100),'rgba(255,94,104,0)')
})
test('transparency stays finite, integer, and bounded',()=>{
  for(const value of [undefined,NaN,Infinity,-Infinity])assert.equal(candleTransparency(value),80)
  assert.equal(candleTransparency(-2),0)
  assert.equal(candleTransparency(102),100)
  assert.equal(candleTransparency(40.6),41)
})
