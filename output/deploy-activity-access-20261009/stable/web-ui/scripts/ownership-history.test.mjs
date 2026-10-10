import test from 'node:test'
import assert from 'node:assert/strict'
import { ownershipHistory, currentOwners } from '../src/ownership-evidence.ts'
import { analyzeChanlun, analyzeIndustry, replayChanlun, replayChanlunComparison } from '../src/api.ts'

test('summary mode lists every historical address, not just current versions', () => {
  const old = { id: 'old', known_index: 100 }, now = { id: 'now', known_index: 200, levels: [] }
  const data = { history_format: 'summary_v1', history_summaries: [old, now], versions: [now], current_owner_ids: ['now'] }
  assert.deepEqual(ownershipHistory(data), [old, now])
  assert.deepEqual(currentOwners(data), [now])
  assert.deepEqual(ownershipHistory(data).slice().reverse(), [now, old])
  assert.deepEqual(data.history_summaries, [old, now])
})

test('full and missing legacy snapshots stay readable without inventing history', () => {
  const old = { id: 'old' }
  assert.deepEqual(ownershipHistory(), [])
  assert.deepEqual(ownershipHistory({ versions: [old] }), [old])
  assert.deepEqual(ownershipHistory({ versions: [], history_format: 'summary_v1', history_summaries: [] }), [])
  assert.deepEqual(ownershipHistory({ versions: [old], history_format: 'future', history_summaries: [] }), [old])
})

test('all four analysis paths explicitly request summary delivery without changing input', async () => {
  const original = globalThis.fetch, calls = [], payload = { marker: 'unchanged' }
  globalThis.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) })
    return { ok: true, json: async () => payload }
  }
  try {
    const requests = [
      [analyzeChanlun, 'analyze', { market: 'SZ', code: '000001', category: 'DAY', count: 600, start: 7 }],
      [analyzeIndustry, 'industry', { stock_market: 'SZ', stock_code: '000001', board_code: '881155', category: 'DAY', count: 600 }],
      [replayChanlun, 'replay', { code: '000001', category: 'DAY', bars: [], visible_count: 20 }],
      [replayChanlunComparison, 'replay/compare', { stock: { code: '000001', bars: [], visible_count: 20 }, industry: { code: '881155', bars: [] } }],
    ]
    for (const [call, path, input] of requests) {
      const saved = structuredClone(input)
      assert.equal(await call(input), payload)
      assert.deepEqual(calls.at(-1), { url: `/api/v1/chanlun/${path}?ownership_history=summary`, body: input })
      assert.deepEqual(input, saved)
    }
  } finally { globalThis.fetch = original }
})
