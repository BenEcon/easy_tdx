import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import vm from 'node:vm'
import {parse,compileScript} from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as radar from '../src/radar-review.ts'
import * as market from '../src/market.ts'
import * as input from '../src/research-input.ts'
import * as origin from '../src/query-origin.ts'

const require=createRequire(import.meta.url),file=new URL('../src/components/SymbolPicker.vue',import.meta.url)
const {descriptor}=parse(readFileSync(file,'utf8'),{filename:file.pathname})
const compiled=ts.transpileModule(compileScript(descriptor,{id:'radar-picker'}).content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
const tick=()=>new Promise(setImmediate)
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
const review={symbol:'300450',category:'DAY',adjust:'QFQ',asOf:'2026-09-30 15:00:00',params:{fast:7,slow:31},evidence:{taskId:'a'.repeat(32),rowIndex:0}}
const snapshot={bars:[{datetime:'2023-01-03T15:00:00',close:20},{datetime:'2026-09-30T15:00:00',close:29}],metadata:{actual_adjust:'QFQ',requested_adjust:'QFQ',category:'DAY'}}
function mount(receive){
  const owner=vue.ref({id:'alice'}),adjust=vue.ref('QFQ'),models={code:vue.ref('300450'),category:vue.ref('DAY'),startDate:vue.ref('2026-01-01'),endDate:vue.ref('2026-10-10')},calls=[],stops=[]
  const store=vue.reactive({ohlcv:[],barsContext:null,error:'',setOhlcv(bars,source,metadata,context){this.ohlcv=bars;this.barsContext=context;calls.push(['loaded',bars,context])},clearResult(){}})
  const mocks={vue:{...vue,useModel:(_,name)=>models[name],onBeforeUnmount:f=>stops.push(f)},'../auth':{useAuth:()=>({currentUser:owner})},'../market':market,'../query-origin':origin,'../radar-review':radar,'../research-input':input,
    '../market-preferences':{useMarketPreferences:()=>({adjustMode:adjust,adjustOptions:[]})},'../stores/backtest':{useBacktestStore:()=>store},
    '../stock-history':{getLastStockCode:()=>'',recordStockHistory:v=>calls.push(['history',v])},
    '../api':{formatError:e=>e.message,fetchBars:async()=>{calls.push(['live']);throw Error('live forbidden')},fetchRadarSnapshot:(...args)=>{calls.push(['frozen',...args]);return receive(...args)}}}
  const mod={exports:{}}
  vm.runInNewContext(compiled,{module:mod,exports:mod.exports,require:p=>mocks[p]??(p.endsWith('.vue')?{}:require(p))},{filename:file.pathname})
  const scope=vue.effectScope(),props=vue.reactive({review:structuredClone(review)})
  const state=scope.run(()=>mod.exports.default.setup(props,{expose(){}}))
  return{state,store,owner,models,calls,close:()=>{stops.forEach(f=>f());scope.stop()}}
}
test('actual picker loads the original complete warmup and stores actual dates, not form defaults',async()=>{
  const h=mount(async()=>snapshot)
  try{
    assert.equal(await h.state.loadBars(),true)
    assert.equal(h.store.ohlcv.length,2)
    assert.equal(h.store.barsContext.startDate,'2023-01-03')
    assert.equal(h.store.barsContext.endDate,'2026-09-30')
    assert.equal(h.calls.find(c=>c[0]==='frozen')[2],'alice')
    assert.equal(h.calls.filter(c=>c[0]==='live').length,0)
  }finally{h.close()}
})
test('failed original input does not fall back to newly fetched prices',async()=>{
  const h=mount(async()=>{throw Error('原任务已清理')})
  try{h.store.ohlcv=[{datetime:'old'}];assert.equal(await h.state.loadBars(),false);assert.equal(h.store.ohlcv.length,0);assert.match(h.store.error,/已清理/);assert.equal(h.calls.filter(c=>c[0]==='live').length,0)}finally{h.close()}
})
for(const change of ['owner','code','unmount'])test(`pending original input cannot commit after ${change}`,async()=>{
  const wait=deferred(),h=mount(()=>wait.promise)
  try{
    const loading=h.state.loadBars();await tick()
    if(change==='owner')h.owner.value={id:'bob'}
    if(change==='code')h.models.code.value='300750'
    if(change==='unmount')h.close()
    wait.resolve(snapshot)
    assert.equal(await loading,false)
    assert.equal(h.store.ohlcv.length,0)
    assert.equal(h.calls.filter(c=>c[0]==='history').length,0)
    assert.equal(h.calls.filter(c=>c[0]==='live').length,0)
  }finally{if(change!=='unmount')h.close()}
})
