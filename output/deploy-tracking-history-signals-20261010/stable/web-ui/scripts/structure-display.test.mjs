import test from 'node:test'
import assert from 'node:assert/strict'
import { structureDate } from '../src/structure-display.ts'

test('structure dates remove midnight noise without changing intraday precision', () => {
  assert.equal(structureDate('2026-10-05T00:00:00'), '2026-10-05')
  assert.equal(structureDate('2026-10-05 00:00:00'), '2026-10-05')
  assert.equal(structureDate('2026-10-05T09:45:01'), '2026-10-05 09:45:01')
  assert.equal(structureDate('2026-10-05 09:45:00'), '2026-10-05 09:45:00')
  assert.equal(structureDate('2026-10-05'), '2026-10-05')
  assert.equal(structureDate(null), '—')
  assert.equal(structureDate('2026-10-05T00:00:00+08:00'), '2026-10-05 00:00:00+08:00')
})
