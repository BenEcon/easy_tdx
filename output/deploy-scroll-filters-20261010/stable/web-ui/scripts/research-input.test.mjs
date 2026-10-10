import { test } from 'node:test'
import assert from 'node:assert/strict'
import { latestResearchRequest, researchInputFields } from '../src/research-input.ts'

test('late old responses cannot own a newer research request', () => {
  const requests = latestResearchRequest()
  const first = requests.begin()
  const second = requests.begin()
  assert.equal(first.signal.aborted, true)
  assert.equal(first.current(), false)
  assert.equal(second.current(), true)
  requests.invalidate()
  assert.equal(second.current(), false)
  assert.equal(second.signal.aborted, true)
})

test('submission fields are captured values, not mutable form references', () => {
  const loaded = {code:'300750',market:'SZ',category:'MIN_30',adjust:'QFQ',startDate:'2026-08-03',endDate:'2026-08-06'}
  const fields = researchInputFields(loaded)
  loaded.code = '300450'
  loaded.category = 'DAY'
  assert.deepEqual(fields, {symbol:'SZ:300750',category:'MIN_30',adjust:'QFQ',start_date:'2026-08-03',end_date:'2026-08-06'})
  assert.deepEqual(researchInputFields(null), {})
})
