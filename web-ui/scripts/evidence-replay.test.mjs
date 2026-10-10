import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceReplayRequest, selectEvidenceSource } from '../src/evidence-replay.ts'

const day = { category: 'DAY', bars: [{ datetime: '2026-09-11', is_closed: true }, { datetime: '2026-09-14', is_closed: true }], result: { code: '300750' } }
const minute = { category: 'MIN_30', bars: [{ datetime: '2026-09-14 10:00', is_closed: true }], result: { code: '300750' } }
test('selects the exact source without replacing missing comparison periods with the primary', () => {
  assert.equal(selectEvidenceSource([day, minute], 'MIN_30'), minute)
  assert.equal(selectEvidenceSource([day, minute], 'DAY'), day)
  assert.equal(selectEvidenceSource([day, minute], 'MIN_5'), null)
  assert.equal(selectEvidenceSource([], 'DAY'), null)
})
test('prefix audit preserves original warmup snapshot and its own instrument and period', () => {
  const request = evidenceReplayRequest(day, 1)
  assert.equal(request.bars, day.bars)
  assert.deepEqual(request, { code: '300750', category: 'DAY', bars: day.bars, visible_count: 1 })
  assert.equal(evidenceReplayRequest(minute, 1).category, 'MIN_30')
  assert.equal(day.bars.length, 2)
})
test('rejects invalid positions, missing identity and explicitly unclosed prefix data', () => {
  for (const position of [0, -1, 3, NaN, Infinity, 1.5, '1', true]) assert.throws(() => evidenceReplayRequest(day, position))
  assert.throws(() => evidenceReplayRequest({ ...day, result: { code: '' } }, 1))
  const unfinished = { ...day, bars: [day.bars[0], { ...day.bars[1], is_closed: false }] }
  assert.throws(() => evidenceReplayRequest(unfinished, 2))
  assert.equal(evidenceReplayRequest(unfinished, 1).visible_count, 1)
})
