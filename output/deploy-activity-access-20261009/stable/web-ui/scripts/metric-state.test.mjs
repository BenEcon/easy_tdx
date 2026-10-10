import { test } from 'node:test'
import assert from 'node:assert/strict'
import { metricText, resultBasis } from '../src/metric-state.ts'

test('null, true zero, infinities and real 999 are distinct after JSON roundtrip', () => {
  const state = kind => ({ state: kind, reason: 'test' })
  assert.equal(metricText(null, state('positive_infinity')), '∞')
  assert.equal(metricText(null, state('negative_infinity')), '−∞')
  assert.equal(metricText(null, state('unavailable')), '—')
  assert.equal(metricText(null), '—')
  assert.equal(metricText(undefined), '—')
  assert.equal(metricText(''), '—')
  assert.equal(metricText('0'), '—')
  assert.equal(metricText(0, state('finite'), 'percent'), '0.00%')
  assert.equal(metricText(999, state('finite')), '999.00')
  assert.equal(metricText(999), '999.00') // never infer an old sentinel by numeric equality
  assert.equal(metricText(Infinity), '∞')
  assert.equal(metricText(NaN), '—')
  assert.equal(metricText(2.55, undefined, 'bars'), '3 根')
})

test('single, saved and comparison results retain authoritative metric basis', () => {
  const basis = { metric_contract: 'performance-metrics-v1', metric_status: {
    profit_factor: { state: 'positive_infinity', reason: 'no realized losses' },
  } }
  const result = JSON.parse(JSON.stringify({ performance: { profit_factor: null }, config: { performance_basis: basis } }))
  assert.deepEqual(resultBasis(result), basis)
  assert.equal(metricText(result.performance.profit_factor, resultBasis(result).metric_status.profit_factor), '∞')
  assert.deepEqual(resultBasis({ data_provenance: { performance_basis: basis }, config: {} }), basis)
  assert.equal(resultBasis({}), undefined)
})
