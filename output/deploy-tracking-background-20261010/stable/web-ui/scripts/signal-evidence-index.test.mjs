import test from 'node:test'
import assert from 'node:assert/strict'
import { diagnosticEvidenceState, eventEvidenceState, indexEvidenceEvents, indexEvidenceDiagnostics, indexStructureSignals, indexMacdPrompts, signalEvidenceState, filterEvidence } from '../src/signal-evidence-index.ts'

const all = { family: 'all', state: 'all', direction: 'all', query: '' }
const event = (changes = {}) => ({ type: 'macd', bc: true, curr_date: '2026-09-11', prev_date: '2026-08-28',
  msg: '反向笔间距不足', status: 'candidate', direction: 'down', ...changes })
const diagnostic = (changes = {}) => ({ family: 'standard', direction: 'down', status: 'blocked',
  first_candidate_index: null, closed: false, dates: { c_start: '2026-09-11', c_end: '2026-09-15' },
  checks: [{ gate: 'area', passed: false, values: {} }], rejections: [], ...changes })

test('distinguishes no candidate, failed current audit, and actual invalidation without promoting legacy state', () => {
  assert.equal(diagnosticEvidenceState(diagnostic()), 'never')
  assert.equal(diagnosticEvidenceState(diagnostic({ first_candidate_index: 0 })), 'blocked')
  assert.equal(eventEvidenceState(event({ status: 'superseded' })), 'superseded')
  assert.equal(eventEvidenceState(event({ status: undefined, confirmed_date: '2026-09-18' })), 'unrecorded')
})
test('filters independent families and directions without merging special and local dual-line evidence', () => {
  const items = [event(), event({ type: 'macd_wave_special' }), event({ type: 'macd_wave_special', direction: 'up' })]
  assert.deepEqual(filterEvidence(indexEvidenceEvents(items), { ...all, family: 'special', direction: 'down' }), [items[1]])
  assert.deepEqual(filterEvidence(indexEvidenceEvents(items), { ...all, family: 'double' }), [items[0]])
})
test('searches lifecycle dates and failure reasons with all terms required, retaining original source objects', () => {
  const item = event({ status: 'superseded', invalidated_date: '2026-09-18', failure_reason: 'DIF 段内极值未改善' })
  const indexed = indexEvidenceEvents([item])
  assert.deepEqual(filterEvidence(indexed, { ...all, query: '2026-09-18 ＤＩＦ' }), [item])
  assert.deepEqual(filterEvidence(indexed, { ...all, query: '2026-09-17 DIF' }), [])
  assert.equal(filterEvidence(indexed, all)[0], item)
})
test('searches diagnostic rejection history without silently reviving historical candidates', () => {
  const item = diagnostic({ first_candidate_index: 3, rejections: [{ from_date: '2026-08-01', through_date: '2026-08-02', gates: ['b_dif_single_excursion'] }] })
  const indexed = indexEvidenceDiagnostics([item])
  assert.deepEqual(filterEvidence(indexed, { ...all, state: 'blocked', query: '2026-08-01' }), [item])
  assert.deepEqual(filterEvidence(indexed, { ...all, state: 'candidate' }), [])
  assert.deepEqual(filterEvidence(indexed, { ...all, state: 'superseded' }), [])
})
test('all excludes bc false, preserves input order and records, and does not infer missing direction', () => {
  const items = [event(), event({ direction: undefined }), event({ bc: false })]
  const before = JSON.stringify(items)
  const indexed = indexEvidenceEvents(items)
  assert.deepEqual(filterEvidence(indexed, all), [items[1], items[0]])
  assert.deepEqual(filterEvidence(indexed, { ...all, direction: 'down' }), [items[0]])
  assert.equal(JSON.stringify(items), before)
})
test('legacy diagnostic family is standard, and empty diagnostics do not invent rejection records', () => {
  const item = diagnostic({ family: undefined })
  assert.deepEqual(filterEvidence(indexEvidenceDiagnostics([item]), { ...all, family: 'standard' }), [item])
  assert.deepEqual(indexEvidenceDiagnostics([]), [])
})

test('structural points retain their own confirmation and evidence, never deriving them from a MACD source', () => {
  const old = { type: '1buy', date: '2026-09-11', msg: '旧记录', evidence: { area_ratio: .45 } }
  const confirmed = { type: '2sell', date: '2026-09-12', confirmed_date: '2026-09-18', confirmed_index: 20,
    source: 'confirmed_segment_base_v1', msg: '回试', evidence: { strength: 'weak_new_extreme', rebound_segment: 3 } }
  const input = [old, confirmed], before = JSON.stringify(input)
  const indexed = indexStructureSignals(input)
  assert.equal(signalEvidenceState(old), 'unrecorded')
  assert.deepEqual(filterEvidence(indexed, { ...all, family: 'structure_signal', state: 'confirmed', direction: 'up', query: '2026-09-18 弱二类' }), [confirmed])
  assert.deepEqual(filterEvidence(indexed, { ...all, direction: 'down' }), [old])
  assert.deepEqual(filterEvidence(indexed, { ...all, query: '45.00%' }), []) // do not invent known-version evidence for legacy source
  assert.equal(filterEvidence(indexed, all)[0], confirmed)
  assert.equal(JSON.stringify(input), before)
})
test('M1 uses exact existing gates and remains a separate view of its original standard event', () => {
  const valid = event({ type: 'macd_wave', status: 'confirmed', signal_index: 3, confirmed_index: 5, confirmed_date: '2026-09-18' })
  const input = [valid, { ...valid, type: 'macd_wave_special' }, { ...valid, type: 'macd_wave_nonstandard' },
    { ...valid, type: 'macd' }, { ...valid, status: 'candidate' }, { ...valid, status: 'superseded' },
    { ...valid, confirmed_index: 3 }, { ...valid, confirmed_date: null }, { ...valid, direction: undefined }]
  const before = JSON.stringify(input)
  assert.deepEqual(filterEvidence(indexMacdPrompts(input), { ...all, query: 'ｍ１ 2026-09-18 买入', family: 'macd_prompt' }), [valid])
  assert.deepEqual(filterEvidence(indexMacdPrompts(input), { ...all, family: 'structure_signal' }), [])
  assert.equal(indexEvidenceEvents([valid]).length, 1) // independent original source is not removed
  assert.equal(JSON.stringify(input), before)
})
test('combined date query finds independent point, prompt and event records without deduplication or additive counts', () => {
  const point = { type: '3buy', date: '2026-09-11', confirmed_date: '2026-09-18', msg: '首次回试' }
  const wave = event({ type: 'macd_wave', status: 'confirmed', signal_index: 0, confirmed_index: 3, confirmed_date: '2026-09-18' })
  const filter = { ...all, query: '2026-09-18' }
  assert.deepEqual(filterEvidence(indexStructureSignals([point]), filter), [point])
  assert.deepEqual(filterEvidence(indexMacdPrompts([wave]), filter), [wave])
  assert.deepEqual(filterEvidence(indexEvidenceEvents([wave]), filter), [wave])
  assert.deepEqual(indexStructureSignals([]), [])
  assert.deepEqual(indexMacdPrompts([]), [])
})

test('chart date matches structured lifecycle timestamps, not coincidental prose dates', () => {
  const item = event({ curr_date: '2026-09-11T00:00:00', confirmed_date: '2026-09-18 15:00:00', msg: '文字里提到 2026-09-19' })
  const indexed = indexEvidenceEvents([item])
  for (const date of ['2026-09-11 00:00:00', '2026-09-18']) assert.deepEqual(filterEvidence(indexed, { ...all, date: { date, precision: 'day' } }), [item])
  assert.deepEqual(filterEvidence(indexed, { ...all, date: { date: '2026-09-19', precision: 'day' } }), [])
})
test('minute evidence uses exact exchange-local minute, accepting T/space and refusing missing time', () => {
  const item = event({ curr_date: '2026-09-11T10:30:00', confirmed_date: '2026-09-11 11:00:00' })
  const indexed = indexEvidenceEvents([item])
  assert.deepEqual(filterEvidence(indexed, { ...all, date: { date: '2026-09-11 10:30', precision: 'minute' } }), [item])
  for (const date of ['2026-09-11 10:31', '2026-09-11', 'not-a-date']) assert.deepEqual(filterEvidence(indexed, { ...all, date: { date, precision: 'minute' } }), [])
})
test('chart date includes diagnostic ABC and rejection coverage without inventing open or reversed intervals', () => {
  const item = diagnostic({ dates: { a_start: '2026-09-01', a_end: '2026-09-03', b_start: '2026-09-04', b_end: '2026-09-05', c_start: '2026-09-07', c_end: '2026-09-11' },
    rejections: [{ from_date: '2026-09-12', through_date: '2026-09-14', gates: ['area'] }] })
  const indexed = indexEvidenceDiagnostics([item])
  for (const date of ['2026-09-02', '2026-09-10', '2026-09-13']) assert.deepEqual(filterEvidence(indexed, { ...all, state: 'never', date: { date, precision: 'day' } }), [item])
  for (const date of ['2026-09-06', '2026-09-15']) assert.deepEqual(filterEvidence(indexed, { ...all, date: { date, precision: 'day' } }), [])
  for (const dates of [{ c_start: '2026-09-07' }, { c_start: '2026-09-11', c_end: '2026-09-07' }]) {
    assert.deepEqual(filterEvidence(indexEvidenceDiagnostics([diagnostic({ dates })]), { ...all, date: { date: '2026-09-10', precision: 'day' } }), [])
  }
})
test('date scope combines with all filters for structural points and original M1 sources', () => {
  const point = { type: '1buy', date: '2026-09-11', confirmed_date: '2026-09-18', msg: '结构确认' }
  const focus = { ...all, date: { date: '2026-09-18', precision: 'day' }, direction: 'down' }
  assert.deepEqual(filterEvidence(indexStructureSignals([point]), focus), [point])
  assert.deepEqual(filterEvidence(indexStructureSignals([point]), { ...focus, direction: 'up' }), [])
  const wave = event({ type: 'macd_wave', status: 'confirmed', signal_index: 1, confirmed_index: 3, confirmed_date: '2026-09-18' })
  assert.deepEqual(filterEvidence(indexMacdPrompts([wave]), focus), [wave])
})
