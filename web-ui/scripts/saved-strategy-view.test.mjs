import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as saved from '../src/saved-strategy-input.ts'
import * as navigation from '../src/research-navigation.ts'
import * as market from '../src/market.ts'
import { queryAction } from '../src/query-origin.ts'
import * as execution from '../src/execution-context.ts'
import * as researchInput from '../src/research-input.ts'
import * as backtestArchive from '../src/backtest-archive.ts'
import {connectStrategyPicker} from './strategy-picker-harness.mjs'

const require = createRequire(import.meta.url)
const tick = () => new Promise(setImmediate)
const copy = v => JSON.parse(JSON.stringify(v))
function deferred() { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject} }
const record = () => ({id:'saved-1',name:'Exact context',kind:'single',strategy:'ma_cross',params:{fast:7,slow:31},tags:[],notes:'',context:{symbol:'SH:510300',category:'MIN_30',adjust:'NONE',start_date:'2026-08-03',end_date:'2026-09-30'},trade_config:{cash:500,commission:.0002,min_commission:1.23,stamp_tax:0,slippage:.002,execution:'next_close'}})
const file = new URL('../src/views/BacktestView.vue', import.meta.url)
const {descriptor} = parse(readFileSync(file,'utf8'),{filename:file.pathname})
const script = compileScript(descriptor,{id:'saved-strategy-view'})
const output = ts.transpileModule(script.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
function mount(api = {}) {
  const owner=vue.ref({id:'alice'}),stock=vue.ref('300750'),adjust=vue.ref('HFQ')
  const route=vue.reactive({path:'/',fullPath:'/?savedStrategyId=saved-1',query:{savedStrategyId:'saved-1'}})
  const calls=[],stops=[],starts=[]
  const store=vue.reactive({strategies:[{name:'ma_cross',label:'MA',params:[{name:'fast',default:5},{name:'slow',default:20}]}],result:null,error:'',running:false,
    loadStrategies:api.loadStrategies??(async()=>{}),clearResult(){this.result=null;this.error='';this.running=false},
    setOhlcv(){},async run(req){calls.push(['run',copy(req)]);this.result={performance:{total_return:.1}}},
  })
  const defaults={fetchSavedStrategy:async()=>record(),saveStrategy:async()=>record(),updateSavedStrategy:async()=>record()}
  const mocks={
    vue:{...vue,onMounted:f=>starts.push(f),onBeforeUnmount:f=>stops.push(f)},
    'vue-router':{useRoute:()=>route},'../auth':{useAuth:()=>({currentUser:owner})},
    '../stores/backtest':{useBacktestStore:()=>store},'../stock-history':{useSelectedStock:()=>stock},
    '../market-preferences':{useMarketPreferences:()=>({adjustMode:adjust})},
    '../mobile-settings':{useMobileSettings:()=>({mobile:vue.ref(false),settingsOpen:vue.ref(false)})},
    '../saved-strategy-input':saved,'../execution-context':execution,'../research-navigation':navigation,'../market':market,'../query-origin':{queryAction},
    '../research-input':researchInput,'../backtest-archive':backtestArchive,
    '../radar-review':{readRadarReview:()=>({value:null,error:''}),sameReviewInput:()=>false,sameReviewStrategy:()=>false},
    '../grading':{gradeBacktestResult:()=>null},'../metric-state':{resultBasis:()=>null},
    '../performance-context':{performanceSnapshot:value=>value},
    '../api':{formatError:e=>String(e.message??e),...Object.fromEntries(Object.keys(defaults).map(key=>[key,(...args)=>{
      calls.push([key,...copy(args)]);return(api[key]??defaults[key])(...args)
    }]))},
  }
  const mod={exports:{}}
  vm.runInNewContext(output,{exports:mod.exports,module:mod,require:path=>mocks[path]??(path.endsWith('.vue')?{}:require(path))},{filename:file.pathname})
  const scope=vue.effectScope(),state=scope.run(()=>mod.exports.default.setup({},{expose(){}}))
  scope.run(()=>connectStrategyPicker(state,store))
  state.symbolPicker.value={loadBars:async()=>{calls.push(['loadBars']);return true}}
  return{state,store,route,owner,adjust,calls,start:()=>state.loadRoute(),close:()=>{stops.forEach(f=>f());scope.stop()}}
}
function marketEntry(source='market') {
  return navigation.researchNavigationQuery({target:{kind:'stock',market:'SZ',code:'300450',name:'先导智能'},category:'MIN_30',adjust:'QFQ',count:600,source})
}
for(const source of ['market','boards'])test(`${source} entry preserves local dates and strategy, runs only on explicit request`,async()=>{
  const h=mount()
  try{
    h.route.query=marketEntry(source)
    h.state.startDate.value='2026-06-01';h.state.endDate.value='2026-09-30'
    await h.start()
    assert.equal(h.state.code.value,'300450');assert.equal(h.state.category.value,'MIN_30');assert.equal(h.adjust.value,'QFQ')
    assert.equal(h.state.startDate.value,'2026-06-01');assert.equal(h.state.endDate.value,'2026-09-30')
    assert.deepEqual(h.calls,[])
    await h.state.onRun(true)
    assert.deepEqual(h.calls.map(c=>c[0]),['loadBars','run'])
    assert.equal(h.calls[1][1].strategy,'ma_cross')
    h.state.openSaveForm();await h.state.onSave()
    const sent=h.calls.find(c=>c[0]==='saveStrategy')[1]
    assert.deepEqual(sent.context,{symbol:'SZ:300450',category:'MIN_30',adjust:'QFQ',start_date:'2026-06-01',end_date:'2026-09-30'})
  }finally{h.close()}
})
for(const extra of [{savedStrategyId:'saved-1'},{optimizationContext:'v1'},{autoRun:'1'},{unexpected:'1'}])test(`mixed market context blocks all loading and computation: ${Object.keys(extra)[0]}`,async()=>{
  const h=mount()
  try{
    h.route.query={...marketEntry(),...extra}
    await h.start();await h.state.onRun(true)
    assert.ok(h.state.entryError.value)
    assert.deepEqual(h.calls,[])
  }finally{h.close()}
})
for(const change of ['input','owner'])test(`slow catalog cannot overwrite ${change} with a market entry`,async()=>{
  const wait=deferred(),h=mount({loadStrategies:()=>wait.promise})
  try{
    h.route.query=marketEntry()
    const loading=h.start();await tick()
    if(change==='input')h.state.code.value='600000';else h.owner.value={id:'bob'}
    wait.resolve();await loading
    assert.equal(h.state.code.value,change==='input'?'600000':'300750')
    await h.state.onRun(true);assert.deepEqual(h.calls,[])
  }finally{h.close()}
})
for(const change of ['input','params','owner','failure'])test(`catalog-stage ${change} cannot restore saved inputs or dispatch a task`,async()=>{
  const wait=deferred(),h=mount({loadStrategies:()=>wait.promise})
  try{
    const load=h.start();await tick()
    await h.state.onRun(true)
    assert.equal(h.calls.filter(c=>c[0]==='loadBars').length,0)
    if(change==='input')h.state.cash.value=1234
    if(change==='params')h.state.params.value={fast:99}
    if(change==='owner')h.owner.value={id:'bob'}
    if(change==='failure')wait.reject(Error('catalog unavailable'));else wait.resolve()
    await load
    assert.equal(h.state.catalogLoading.value,false)
    assert.equal(h.state.catalogError.value,true)
    assert.equal(h.calls.filter(c=>c[0]==='fetchSavedStrategy').length,0)
    assert.notEqual(h.state.savedLoadState.value,'ready')
    if(change!=='owner')assert.match(h.store.error,/载入|目录/)
    if(change==='input')assert.equal(h.state.cash.value,1234)
    if(change==='params')assert.deepEqual(h.state.params.value,{fast:99})
    await h.state.onRun(true);assert.equal(h.calls.filter(c=>c[0]==='run').length,0)
    if(change==='input'||change==='params'){
      await h.start();assert.equal(h.state.savedLoadState.value,'ready')
      assert.equal(h.state.cash.value,500)
    }
  }finally{h.close()}
})
test('optimization context restores every execution field and malformed context blocks dispatch',async()=>{
  const h=mount()
  try{
    h.route.query=execution.optimizationQuery({...record().context,...record().trade_config},'ma_cross',{fast:7,slow:31})
    await h.start();assert.equal(h.state.savedLoadState.value,'ready');assert.equal(h.state.minCommission.value,1.23);assert.equal(h.state.stampTax.value,0)
    assert.equal(h.calls.filter(c=>c[0]==='run').length,0)
    await h.state.onRun(true)
    const sent=h.calls.find(c=>c[0]==='run')[1]
    for(const [key,value] of Object.entries(record().trade_config))assert.equal(sent[key],value,key)
    h.route.query={...h.route.query,autoRun:'1'};await h.start();await h.state.onRun(true)
    assert.equal(h.state.savedLoadState.value,'error');assert.equal(h.calls.filter(c=>c[0]==='run').length,1)
  }finally{h.close()}
})
test('actual backtest view loads exact saved context without running, then saves the configuration used',async()=>{
  const h=mount()
  try{
    await h.start()
    assert.equal(h.state.savedLoadState.value,'ready')
    assert.deepEqual(h.calls,[['fetchSavedStrategy','saved-1','alice']])
    assert.equal(h.state.code.value,'510300');assert.equal(h.adjust.value,'NONE')
    await h.state.onRun(true)
    assert.deepEqual(h.calls.find(c=>c[0]==='run')[1],{strategy:'ma_cross',params:{fast:7,slow:31},...record().trade_config})
    h.state.openSaveForm();await h.state.onSave()
    const sent=h.calls.find(c=>c[0]==='saveStrategy')
    assert.equal(sent[2],'alice')
    for(const key of ['context','params','trade_config'])assert.deepEqual(sent[1][key],record()[key])
    assert.equal(h.state.showSaveForm.value,false)
  }finally{h.close()}
})

test('saving original radar warmup uses loaded input dates, not hidden form defaults',async()=>{
  const h=mount()
  try{
    await h.start();await h.state.onRun(true)
    h.store.barsContext={code:'510300',market:'SH',category:'MIN_30',adjust:'NONE',startDate:'2023-01-03',endDate:'2026-09-29'}
    h.state.openSaveForm();await h.state.onSave()
    const sent=h.calls.find(c=>c[0]==='saveStrategy')[1]
    assert.equal(sent.context.start_date,'2023-01-03')
    assert.equal(sent.context.end_date,'2026-09-29')
  }finally{h.close()}
})
for(const reset of ['owner','route','input','unmount'])test(`late saved record cannot overwrite ${reset}`,async()=>{
  const wait=deferred(),h=mount({fetchSavedStrategy:()=>wait.promise})
  try{
    const load=h.start();await tick()
    if(reset==='owner')h.owner.value={id:'bob'}
    if(reset==='input')h.state.cash.value=1234
    if(reset==='route'){h.route.query={};await h.start()}
    if(reset==='unmount')h.close()
    wait.resolve(record());await load
    assert.notEqual(h.state.savedLoadState.value,'ready')
    assert.equal(h.state.code.value,'300750')
    if(reset==='input'){assert.equal(h.state.cash.value,1234);assert.match(h.store.error,/参数已修改/)}
  }finally{if(reset!=='unmount')h.close()}
})
test('invalid saved context blocks run, while legacy missing fields disclose fallback',async()=>{
  for(const invalid of ['id','strategy','adjust']){
    const bad=record();if(invalid==='adjust')bad.context.adjust='bad';else bad[invalid]='different'
    const h=mount({fetchSavedStrategy:async()=>bad})
    try{await h.start();await h.state.onRun(true);assert.equal(h.state.savedLoadState.value,'error');assert.equal(h.calls.length,1)}finally{h.close()}
  }
  const old=record();old.trade_config={};old.context={symbol:'000001'}
  const h=mount({fetchSavedStrategy:async()=>old})
  try{await h.start();assert.equal(h.state.savedLoadWarnings.value.length,11);assert.equal(h.state.savedLoadState.value,'ready')}finally{h.close()}
})
test('every execution input invalidates the old result before it can be saved',async()=>{
  for(const [field,value] of [['code','600000'],['category','DAY'],['adjustMode','HFQ'],['startDate','2026-08-04'],['endDate','2026-09-29'],['strategy','macd'],['params',{fast:8,slow:31}],['cash',600],['commission',.0004],['minCommission',2.34],['stampTax',.001],['slippage',.003],['execution','next_open']]){
    const h=mount()
    try{
      await h.start();await h.state.onRun(true);h.state.openSaveForm()
      h.state[field].value=value
      assert.equal(h.store.result,null,field)
      await h.state.onSave()
      assert.equal(h.calls.filter(c=>c[0]==='saveStrategy').length,0,field)
    }finally{h.close()}
  }
})
test('editing a cost while bars are pending never runs the new form on the old request',async()=>{
  const h=mount(),wait=deferred()
  try{
    await h.start();h.state.symbolPicker.value={loadBars:()=>wait.promise}
    const run=h.state.onRun(true)
    h.state.minCommission.value=9
    wait.resolve(true);await run
    assert.equal(h.calls.filter(c=>c[0]==='run').length,0)
  }finally{h.close()}
})
for(const reset of ['owner','route','unmount'])test(`save completion after ${reset} cannot write into a different page or account`,async()=>{
  const wait=deferred(),h=mount({saveStrategy:()=>wait.promise})
  try{
    await h.start();await h.state.onRun(true);h.state.openSaveForm()
    const saving=h.state.onSave()
    await h.state.onSave();assert.equal(h.calls.filter(c=>c[0]==='saveStrategy').length,1)
    if(reset==='owner')h.owner.value={id:'bob'}
    if(reset==='route'){h.route.query={};await h.start()}
    if(reset==='unmount')h.close()
    wait.resolve(record());await saving
    assert.equal(h.state.saveMsg.value,'')
  }finally{if(reset!=='unmount')h.close()}
})
