import test from 'node:test'
import assert from 'node:assert/strict'
import { alignPeriodSnapshots, comparisonPeriods } from '../src/period-comparison.ts'

const bar = (date, end, closed = true) => ({ datetime: date, period_end: end, is_closed: closed })
const snapshot = (bars, adjust = 'QFQ', observed = '2026-10-05 16:00:00') => ({ bars, metadata: { actual_adjust: adjust, observed_at: observed } })
const daily = snapshot([bar('2026-09-30T00:00:00', '2026-09-30 15:00:00'), bar('2026-10-05 00:00:00', '2026-10-05 15:00:00', false)])
const minutes = snapshot([bar('2026-09-30 14:00:00', '2026-09-30 14:30:00'), bar('2026-09-30 14:30:00', '2026-09-30 15:00:00'), bar('2026-10-05 14:30:00', '2026-10-05 15:00:00')])
test('both periods exclude future and open candles while retaining original warm-up start', () => {
  const aligned = alignPeriodSnapshots(daily, minutes, '2026-09-30 15:00:00', 'QFQ')
  assert.equal(aligned.primary.bars.length, 1)
  assert.equal(aligned.other.bars.length, 2)
  assert.equal(aligned.primary.bars[0], daily.bars[0])
  assert.equal(aligned.other.bars[0], minutes.bars[0])
  assert.equal(daily.bars.length, 2)
})
test('snapshot observation time caps cutoff; bar start before cutoff is not enough', () => {
  const early = snapshot(minutes.bars, 'QFQ', '2026-09-30 14:45:00')
  const aligned = alignPeriodSnapshots(daily, early, '2026-10-05 16:00:00', 'QFQ')
  assert.equal(aligned.cutoff, '2026-09-30 14:45:00')
  assert.equal(aligned.other.bars.length, 1)
  assert.equal(aligned.primary.bars.length, 0)
})
test('no timeframe fallback or fabricated candles when historical minute range is unavailable', () => {
  const aligned = alignPeriodSnapshots(daily, minutes, '2026-09-01 15:00:00', 'QFQ')
  assert.equal(aligned.other.bars.length, 0)
})
test('index and board snapshots retain NONE adjustment, mismatch is rejected', () => {
  assert.equal(alignPeriodSnapshots(snapshot(daily.bars, 'NONE'), snapshot(minutes.bars, 'NONE'), '2026-10-05 16:00:00', 'NONE').other.bars.length, 3)
  assert.throws(() => alignPeriodSnapshots(daily, snapshot(minutes.bars, 'NONE'), '2026-10-05 16:00:00', 'QFQ'), /复权/)
})
test('missing completion evidence, timezone timestamps and unordered bars fail explicitly', () => {
  for (const bad of [bar('2026-09-30 14:00:00', undefined), { ...minutes.bars[0], is_closed: undefined },
    bar('2026-09-30T14:00:00Z', '2026-09-30 14:30:00'), bar('2026-09-30 14:00:00', '2026-09-30 13:30:00')]) {
    assert.throws(() => alignPeriodSnapshots(daily, snapshot([bad]), '2026-10-05 16:00:00', 'QFQ'))
  }
  assert.throws(() => alignPeriodSnapshots(daily, snapshot([...minutes.bars].reverse()), '2026-10-05 16:00:00', 'QFQ'), /顺序/)
})
test('week/month completion boundary comes from provider annotation, not day label', () => {
  const weekly = snapshot([bar('2026-09-28 00:00:00', '2026-10-02 15:00:00')])
  assert.equal(alignPeriodSnapshots(daily, weekly, '2026-09-30 15:00:00', 'QFQ').other.bars.length, 0)
  assert.equal(comparisonPeriods.length, 8)
  assert.ok(!comparisonPeriods.some(item => item.value === 'MIN_120'))
})
