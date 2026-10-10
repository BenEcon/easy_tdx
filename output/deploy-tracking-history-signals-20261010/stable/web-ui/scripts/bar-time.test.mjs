import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createBarTimeLookup, formatMarketTime } from '../src/bar-time.ts'

test('trade lookup keeps the exact minute across separators, precision and days', () => {
  const find = createBarTimeLookup(['2026-10-09 09:35:00', '2026-10-09 09:40:00', '2026-10-12T09:35:00'])
  assert.equal(find('2026-10-09T09:40:00.000000000'), 1)
  assert.equal(find('2026-10-12 09:35'), 2)
  assert.equal(find('2026-10-09T09:39:00'), undefined)
  assert.equal(find('2026-10-09'), undefined)
  assert.equal(find('2026-10-12'), 2) // one unique bar that day
})

test('date-only values cannot choose the midnight bar of an ambiguous day', () => {
  const find = createBarTimeLookup(['2026-10-09T00:00:00', '2026-10-09T00:05:00'])
  assert.equal(find('2026-10-09'), undefined)
  assert.equal(find('2026-10-09T00:00:00'), 0)
})

test('daily and duplicate exact timestamps keep first positional matches', () => {
  const find = createBarTimeLookup(['2026-10-09', '2026-10-09T00:00:00', '2026-10-12'])
  assert.equal(find('2026-10-09T00:00:00'), 0)
  assert.equal(find('2026-10-09'), 0)
  assert.equal(find('2026-10-12T09:35:00'), undefined)
  assert.equal(find('invalid'), undefined)
})

test('nanoseconds and timezone text are not truncated into a false match', () => {
  const find = createBarTimeLookup(['2026-10-09T09:35:00.000000123', '2026-10-09T09:35:00.000000124'])
  assert.equal(find('2026-10-09 09:35:00.000000124'), 1)
  assert.equal(find('2026-10-09T09:35:00'), undefined)
  assert.equal(find('2026-10-09T09:35:00.000000124Z'), undefined)
})

test('date labels preserve useful precision without local timezone conversion', () => {
  assert.equal(formatMarketTime('2026-10-09T00:00:00'), '2026-10-09')
  assert.equal(formatMarketTime('2026-10-09T09:35:00'), '2026-10-09 09:35')
  assert.equal(formatMarketTime('2026-10-09T09:35:01.123000000'), '2026-10-09 09:35:01.123')
  assert.equal(formatMarketTime('2026-10-09T09:35:00+08:00'), '2026-10-09 09:35+08:00')
})
