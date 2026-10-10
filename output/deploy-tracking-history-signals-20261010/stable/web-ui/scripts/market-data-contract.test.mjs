import { test } from 'node:test'
import assert from 'node:assert/strict'
import { assertMarketData, adjustmentName } from '../src/market-data-contract.ts'
import { fetchBars } from '../src/api.ts'

test('aborted late response cannot publish metadata even if transport ignores abort', async t => {
  const controller = new AbortController()
  let notified = false
  t.mock.method(globalThis, 'fetch', async () => {
    controller.abort()
    return new Response(JSON.stringify({metadata:{actual_adjust:'QFQ',requested_adjust:'QFQ'},data:[]}))
  })
  await assert.rejects(fetchBars('SZ','300750','DAY',undefined,undefined,'QFQ',
    () => { notified = true }, controller.signal), {name:'AbortError'})
  assert.equal(notified, false)
})

test('missing provenance or silently changed adjustment never reaches research', () => {
  assert.throws(() => assertMarketData(undefined, 'QFQ'), /缺少/)
  assert.throws(() => assertMarketData({actual_adjust:'NONE',requested_adjust:'QFQ'}, 'QFQ'), /不一致/)
  assert.throws(() => assertMarketData({actual_adjust:'QFQ',requested_adjust:'QFQ',quality:{status:'error',errors:['时间重复']}}, 'QFQ'), /时间重复/)
})
test('reported gaps do not falsely label suspension or prevent inspecting valid candles', () => {
  assert.doesNotThrow(() => assertMarketData({actual_adjust:'QFQ',requested_adjust:'QFQ',quality:{status:'warning',warnings:['缺失未核验']}}, 'QFQ'))
  assert.equal(adjustmentName('QFQ'),'前复权')
  assert.equal(adjustmentName('HFQ'),'后复权')
  assert.equal(adjustmentName('NONE'),'不复权')
})

test('history fetch consumes one verified range and publishes complete metadata only after validation', async t => {
  const metadata = {actual_adjust:'QFQ', requested_adjust:'QFQ', page_count:3, range_start:'2025-01-01', range_end:'2026-09-30'}
  let requested
  t.mock.method(globalThis, 'fetch', async url => {
    requested = String(url)
    return new Response(JSON.stringify({metadata, data:[{datetime:'2025-01-01',is_closed:true,open:10,high:11,low:9,close:10,vol:10,amount:100}]}))
  })
  let received
  const bars = await fetchBars('SH','603936','DAY','2025-01-01','2026-09-30','QFQ', value => { received = value })
  assert.equal(bars.length,1)
  assert.deepEqual(received,metadata)
  assert.match(requested,/\/bars\/range\?/)
  assert.match(requested,/start_date=2025-01-01/)
})

test('unclosed response never updates provenance or reaches the backtest', async t => {
  let notified = false
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    metadata:{actual_adjust:'QFQ',requested_adjust:'QFQ'},
    data:[{datetime:'2026-09-30',is_closed:false}],
  })))
  await assert.rejects(fetchBars('SH','603936','DAY',undefined,undefined,'QFQ', () => { notified = true }), /未确认收盘/)
  assert.equal(notified,false)
})
