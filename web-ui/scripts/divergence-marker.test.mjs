import test from 'node:test'
import assert from 'node:assert/strict'
import { divergenceMarker, macdPrompts } from '../src/divergence-marker.ts'

test('direction, family and lifecycle have independent marker styles', () => {
  for (const direction of ['up', 'down']) {
    for (const type of ['macd', 'macd_wave', 'qs', 'pz']) {
      const base = { bc: true, type, direction }
      const pending = divergenceMarker({ ...base, status: 'candidate' })
      const confirmed = divergenceMarker({ ...base, status: 'confirmed' })
      assert.equal(pending.symbol, type === 'macd' ? 'circle' : 'diamond')
      assert.equal(pending.itemStyle.color, 'transparent')
      assert.equal(pending.itemStyle.borderType, 'dashed')
      assert.equal(confirmed.itemStyle.color, direction === 'up' ? '#61dfa0' : '#cf8ff5')
      assert.equal(confirmed.itemStyle.borderType, 'solid')
      assert.equal(divergenceMarker({ ...base, status: 'superseded' }), null)
      assert.equal(divergenceMarker({ ...base, bc: false }), null)
    }
  }
})

test('M1 is restricted to confirmed waves with a later actual confirmation', () => {
  const base = { bc: true, type: 'macd_wave', status: 'confirmed', direction: 'down',
    signal_index: 10, confirmed_index: 13, curr_date: '2026-09-11', confirmed_date: '2026-09-16' }
  for (const direction of ['up', 'down']) {
    const event = { ...base, direction }
    assert.deepEqual(macdPrompts([event]), [event])
  }
  for (const change of [{ type: 'qs' }, { type: 'macd' }, { status: 'candidate' },
    { status: 'superseded' }, { bc: false }, { confirmed_index: 10 },
    { confirmed_index: null }, { signal_index: -1 }, { direction: undefined },
    { confirmed_date: null }]) {
    assert.deepEqual(macdPrompts([{ ...base, ...change }]), [])
  }
})
