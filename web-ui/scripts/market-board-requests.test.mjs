import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import { latestResearchRequest } from '../src/research-input.ts'
import { queryAction, queryIntentHeaders } from '../src/query-origin.ts'
import * as navigation from '../src/research-navigation.ts'

const require = createRequire(import.meta.url)
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
// Run the actual SFC setup and Vue synchronous watchers, with delayed transport.
// This verifies view assignments and finally blocks, not just the request helper.
function mount(name, api = {}) {
  const file = new URL(`../src/views/${name}.vue`, import.meta.url)
  const { descriptor } = parse(readFileSync(file, 'utf8'), { filename: file.pathname })
  const script = compileScript(descriptor, { id: name })
  const output = ts.transpileModule(script.content, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText
  const owner = vue.ref({ id: 'alice' }), stock = vue.ref('300750'), history = []
  const starts = [], stops = [], calls = []
  const apiProxy = new Proxy({ formatError: e => String(e?.message ?? e) }, {
    get(target, key) {
      if (key in target) return target[key]
      return (...args) => {
        calls.push({ name: key, args, origin: queryIntentHeaders()['X-Query-Origin'] })
        if (!api[key]) throw Error(`Unexpected API: ${key}`)
        return api[key](...args)
      }
    },
  })
  const mod = { exports: {} }
  const scope = vue.effectScope()
  const mocks = {
    vue: { ...vue, onMounted: f => starts.push(f), onBeforeUnmount: f => stops.push(f) },
    '../auth': { useAuth: () => ({ currentUser: owner }) },
    '../api': apiProxy,
    '../research-input': { latestResearchRequest },
    '../research-navigation': navigation,
    '../query-origin': { queryAction },
    '../market': { detectMarket: code => code.startsWith('6') ? 'SH' : 'SZ' },
    '../stock-history': { useSelectedStock: () => stock, recordStockHistory: r => history.push(r) },
  }
  vm.runInNewContext(output, { exports: mod.exports, module: mod, AbortController,
    require: path => mocks[path] ?? (path.endsWith('.vue') ? {} : require(path)),
  }, { filename: file.pathname })
  const state = scope.run(() => mod.exports.default.setup({}, { expose() {} }))
  return { state, owner, stock, history, calls, start: () => starts.map(f => f()),
    close: () => { stops.forEach(f => f()); scope.stop() } }
}

test('market tab changes discard old success and cannot stop the new spinner', async () => {
  const old = deferred(), next = deferred()
  const h = mount('MarketCenterView', { fetchMarketRanking: () => old.promise, fetchMarketStat: () => next.promise })
  try {
    const first = h.state.load(true)
    h.state.tab.value = 'stat'
    const second = h.state.load(true)
    old.resolve({ data: [{ code: '300750' }] }); await first
    assert.equal(h.state.rows.value.length, 0)
    assert.equal(h.state.loading.value, true)
    next.resolve({ data: [{ label: 'up' }] }); await second
    assert.equal(h.state.rows.value[0].label, 'up')
    assert.equal(h.state.loading.value, false)
  } finally { h.close() }
})

for (const reset of ['filter', 'owner', 'unmount']) test(`market late failure after ${reset} cannot resurrect an error`, async () => {
  const wait = deferred()
  const h = mount('MarketCenterView', { fetchMarketRanking: () => wait.promise })
  const run = h.state.load()
  if (reset === 'filter') h.state.category.value = 'SZ'
  else if (reset === 'owner') h.owner.value = { id: 'bob' }
  else h.close()
  wait.reject(Error('old server failed')); await run
  assert.equal(h.state.error.value, '')
  assert.equal(h.state.loading.value, false)
  assert.equal(h.state.rows.value.length, 0)
  if (reset !== 'unmount') h.close()
})

test('directory count failure preserves valid rows; late totals cannot cross markets', async () => {
  const totals = [deferred(), deferred()]
  const h = mount('MarketCenterView', {
    fetchSecurityDirectory: async market => ({ data: [{ code: market === 'SH' ? '600000' : '000001' }] }),
    fetchSecurityCount: market => totals[market === 'SH' ? 0 : 1].promise,
  })
  try {
    h.state.tab.value = 'directory'
    const first = h.state.load(true); await new Promise(setImmediate)
    h.state.directoryMarket.value = 'SZ'
    const second = h.state.load(true); await new Promise(setImmediate)
    totals[0].resolve({ count: 100 }); await first
    assert.equal(h.state.securityTotal.value, null)
    assert.equal(h.state.loading.value, true)
    totals[1].reject(Error('count unavailable')); await second
    assert.equal(h.state.rows.value[0].code, '000001')
    assert.match(h.state.error.value, /市场总数暂不可用/)
    assert.deepEqual(h.calls.map(c => c.origin), ['user', 'system', 'user', 'system'])
  } finally { h.close() }
})

test('board selection clears old details and ignores slower preceding member responses', async () => {
  const a = deferred(), b = deferred()
  const h = mount('BoardResearchView', {
    fetchBoardMembers: code => (code === '880001' ? a : b).promise,
    fetchBoardSummary: async code => ({ data: { code } }),
  })
  try {
    h.state.members.value = [{ code: 'stale' }]
    const first = h.state.selectBoard({ code: '880001', name: 'A' }, true)
    assert.equal(h.state.members.value.length, 0)
    const second = h.state.selectBoard({ code: '880002', name: 'B' }, true)
    assert.equal(h.calls[0].args[2].aborted, true)
    a.resolve({ data: [{ code: 'from A' }] }); await first
    assert.equal(h.state.members.value.length, 0)
    assert.equal(h.state.loadingMembers.value, true)
    b.resolve({ data: [{ code: 'from B' }] }); await second
    assert.equal(h.state.selectedName.value, 'B')
    assert.equal(h.state.members.value[0].code, 'from B')
    assert.equal(h.state.summary.value.code, '880002')
    assert.deepEqual(h.calls.map(c => c.origin), ['user', 'system', 'user', 'system'])
  } finally { h.close() }
})

test('board list filter changes invalidate pending member requests and prevent old auto-selection', async () => {
  const list = deferred(), member = deferred()
  const h = mount('BoardResearchView', {
    fetchBoardList: () => list.promise,
    fetchBoardMembers: () => member.promise,
    fetchBoardSummary: async () => ({ data: {} }),
  })
  try {
    const first = h.state.loadBoards(true)
    h.state.boardType.value = 'GN'
    list.resolve({ data: [{ code: '880001', name: 'old industry' }] }); await first
    assert.equal(h.state.boards.value.length, 0)
    assert.equal(h.calls.length, 1)
    const selected = h.state.selectBoard({ code: '880002' }, true)
    h.state.mode.value = 'classic'
    member.reject(Error('old members')); await selected
    assert.equal(h.state.memberError.value, '')
    assert.equal(h.state.selectedBoard.value, null)
    assert.equal(h.state.loadingMembers.value, false)
  } finally { h.close() }
})

test('default board preload remains system-origin after manual list refresh', async () => {
  const h = mount('BoardResearchView', {
    fetchBoardList: async () => ({ data: [{ code: '880001' }] }),
    fetchBoardMembers: async () => ({ data: [] }),
    fetchBoardSummary: async () => ({ data: {} }),
  })
  try {
    await h.state.loadBoards(true)
    await Promise.resolve()
    assert.deepEqual(h.calls.map(c => c.origin), ['user', 'system', 'system'])
  } finally { h.close() }
})

for (const reset of ['stock', 'owner', 'unmount']) test(`belonging response after ${reset} cannot change results or stock history`, async () => {
  const wait = deferred()
  const h = mount('BoardResearchView', { fetchBoardBelong: () => wait.promise })
  const run = h.state.queryBelong()
  if (reset === 'stock') h.stock.value = '600000'
  else if (reset === 'owner') h.owner.value = { id: 'bob' }
  else h.close()
  wait.resolve({ data: [{ board_code: '880001' }] }); await run
  assert.equal(h.state.belongs.value.length, 0)
  assert.equal(h.history.length, 0)
  assert.equal(h.state.loadingBelong.value, false)
  if (reset !== 'unmount') h.close()
})

test('current belonging success records captured stock; concurrent member failure has separate feedback', async () => {
  const h = mount('BoardResearchView', {
    fetchBoardBelong: async () => ({ data: [{ board_code: '880001' }] }),
    fetchBoardMembers: async () => { throw Error('member failed') },
    fetchBoardSummary: async () => ({ data: {} }),
  })
  try {
    await Promise.all([h.state.queryBelong(), h.state.selectBoard({ code: '880001' }, true)])
    assert.equal(h.state.belongs.value.length, 1)
    assert.equal(h.history[0].code, '300750')
    assert.match(h.state.memberError.value, /member failed/)
    assert.equal(h.state.belongError.value, '')
    assert.equal(h.state.error.value, '')
  } finally { h.close() }
})

test('market selection uses loaded market, clears on filters, and distinguishes shared stock/index codes', async () => {
  const h = mount('MarketCenterView', { fetchSecurityDirectory: async () => ({ data: [{code:'000001',name:'Test'}] }), fetchSecurityCount: async () => ({count:1}) })
  try {
    h.state.tab.value = 'directory'
    await h.state.load()
    h.state.selectRow(h.state.rows.value[0])
    assert.equal(h.state.selection.value.target.kind, 'index')
    h.state.directoryMarket.value = 'SZ'
    assert.equal(h.state.selection.value, null)
    await h.state.load()
    h.state.selectRow(h.state.rows.value[0])
    assert.equal(h.state.selection.value.target.kind, 'stock')
    assert.equal(h.state.selection.value.target.market, 'SZ')
    h.owner.value = {id:'bob'}
    assert.equal(h.state.selection.value, null)
  } finally {h.close()}
})

test('board analysis uses result classification; members require their own market', async () => {
  const h = mount('BoardResearchView', {
    fetchBoardList: async () => ({data:[{code:'880001',market:1,name:'Industry'}]}),
    fetchBoardMembers: async () => ({data:[{code:'000001',market:0,name:'Bank'}]}),
    fetchBoardSummary: async () => ({data:{}}),
  })
  try {
    await h.state.loadBoards()
    await new Promise(setImmediate)
    assert.equal(h.state.boardSelection.value.target.boardType, 'HY')
    h.state.selectMember(h.state.members.value[0])
    assert.equal(h.state.memberSelection.value.target.market, 'SZ')
    h.state.selectMember({code:'000001'})
    assert.equal(h.state.memberSelection.value.target, null)
    h.state.boardType.value = 'ALL'
    await h.state.loadBoards(); await new Promise(setImmediate)
    assert.equal(h.state.boardSelection.value.target, null)
    assert.match(h.state.boardSelection.value.error, /分类不明确/)
  } finally {h.close()}
})
