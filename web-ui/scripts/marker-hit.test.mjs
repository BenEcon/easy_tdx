import test from 'node:test'
import assert from 'node:assert/strict'
import { markerHit } from '../src/marker-hit.ts'
test('marker hit uses signed stacking offset for both directions, not candle position', () => {
  assert.equal(markerHit([100,200],[0,23],9,100,223),true)
  assert.equal(markerHit([100,200],[0,-36],13,100,164),true)
  assert.equal(markerHit([100,200],[0,23],9,100,200),false)
  assert.equal(markerHit([100,200],[0,23],9,108,223),false)
})
test('symbol size and invalid render positions are handled safely', () => {
  assert.equal(markerHit([100,200],[0,23],[20,13],111,223),true)
  assert.equal(markerHit([NaN,200],[0,23],9,100,223),false)
  assert.equal(markerHit([],[],9,0,0),false)
  assert.equal(markerHit([100,200],[0,23],9,NaN,223),false)
})
