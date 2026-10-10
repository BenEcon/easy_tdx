import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import vm from 'node:vm'
import {parse,compileScript} from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as tasks from '../src/task-execution.ts'
import * as radar from '../src/radar-review.ts'
import {queryIntentHeaders} from '../src/query-origin.ts'

const require=createRequire(import.meta.url),tick=()=>new Promise(setImmediate)
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{resolve,reject,promise}}
const scan=()=>({rows:[],total:0,buy_count:0,sell_count:0,error_count:0,elapsed:.1})
const done=(id='scan')=>({task_id:id,status:'done',result:scan()})
const old=()=>({schema:'radar-cache-v2',owner:'alice',result:scan(),scannedAt:'previous',windowBars:5,adjust:'HFQ'})
const file=new URL('../src/views/SignalRadarView.vue',import.meta.url)
const {descriptor}=parse(readFileSync(file,'utf8'),{filename:file.pathname})
const compiled=ts.transpileModule(compileScript(descriptor,{id:'radar-lifecycle'}).content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
function mount(api={},cached=null){
  const owner=vue.ref({id:'alice'}),adjust=vue.ref('QFQ'),calls=[],stops=[],cache=new Map(cached?[[radar.radarCacheKey('alice'),JSON.stringify(cached)]]:[])
  const defaults={submitSignalScanTask:async()=>({task_id:'scan'}),fetchTask:async()=>done()}
  const mock={vue:{...vue,onBeforeUnmount:f=>stops.push(f)},'vue-router':{useRouter:()=>({push:q=>calls.push({method:'navigate',q})})},
    '../auth':{useAuth:()=>({currentUser:owner})},'../market-preferences':{useMarketPreferences:()=>({adjustMode:adjust})},
    '../task-execution':tasks,'../radar-review':radar,
    '../api':{formatError:e=>String(e.message??e),...Object.fromEntries(Object.keys(defaults).map(method=>[method,(...args)=>{
      calls.push({method,args,origin:queryIntentHeaders()['X-Query-Origin']});return(api[method]??defaults[method])(...args)
    }]))}}
  const mod={exports:{}}
  const storage={getItem:k=>cache.get(k)??null,setItem:(k,v)=>{if(api.storageError)throw Error('Quota');cache.set(k,v)}}
  vm.runInNewContext(compiled,{exports:mod.exports,module:mod,require:path=>mock[path]??(path.endsWith('.vue')?{}:require(path)),localStorage:storage,Date},{filename:file.pathname})
  const scope=vue.effectScope(),state=scope.run(()=>mod.exports.default.setup({},{expose(){}}))
  return{state,owner,adjust,calls,cache,close:()=>{stops.forEach(f=>f());scope.stop()}}
}
test('radar submits captured owner with manual intent, polls as system, and preserves old cache adjustment',async()=>{
  const h=mount({},old())
  try{
    assert.equal(h.calls.length,0);assert.equal(h.adjust.value,'QFQ');assert.equal(h.state.resultAdjust.value,'HFQ')
    assert.equal(h.state.resultDiffers.value,true);assert.match(h.state.cacheNotice.value,/上次成功/)
    await h.state.onScan()
    assert.equal(h.calls.length,2);assert.deepEqual(h.calls.map(c=>c.origin),['user','system'])
    assert.equal(h.calls[0].args[1].owner,'alice');assert.equal(h.calls[1].args[1],h.calls[0].args[1])
    assert.equal(h.state.resultAdjust.value,'QFQ');assert.equal(h.state.resultDiffers.value,false)
    const saved=JSON.parse(h.cache.get(radar.radarCacheKey('alice')));assert.equal(saved.adjust,'QFQ');assert.equal(saved.result.total,0)
  }finally{h.close()}
})
for(const stage of ['submit','poll'])for(const change of ['adjust','window','owner','roundtrip','unmount'])test(`late ${stage} after ${change} cannot become a scan result or cache`,async()=>{
  const pending=deferred(),h=mount({[stage==='submit'?'submitSignalScanTask':'fetchTask']:()=>pending.promise})
  try{
    const run=h.state.onScan();await tick();await h.state.onScan()
    assert.equal(h.calls.filter(c=>c.method==='submitSignalScanTask').length,1)
    const context=h.calls[0].args[1]
    if(change==='adjust')h.adjust.value='NONE'
    if(change==='window')h.state.windowBars.value=10
    if(change==='owner'||change==='roundtrip')h.owner.value={id:'bob'}
    if(change==='roundtrip')h.owner.value={id:'alice'}
    if(change==='unmount')h.close()
    assert.equal(context.signal.aborted,true)
    pending.resolve(stage==='submit'?{task_id:'scan'}:done());await run
    assert.equal(h.state.result.value,null);assert.equal(h.state.error.value,'');assert.equal(h.state.scanning.value,false);assert.equal(h.cache.size,0)
    if(stage==='submit')assert.equal(h.calls.filter(c=>c.method==='fetchTask').length,0)
    if(change==='adjust'||change==='window')assert.match(h.state.detachedNotice.value,/后台任务未取消/)
  }finally{if(change!=='unmount')h.close()}
})
test('a failed new scan cannot re-display or replace old success; explicit retry is independent',async()=>{
  let failure=true;const h=mount({fetchTask:async()=>failure?{task_id:'scan',status:'failed',error:'feed unavailable'}:done()},old())
  try{
    await h.state.onScan();assert.equal(h.state.result.value,null);assert.equal(h.state.scannedAt.value,'');assert.match(h.state.error.value,/feed unavailable/)
    assert.equal(JSON.parse(h.cache.get(radar.radarCacheKey('alice'))).scannedAt,'previous')
    failure=false;await h.state.onScan();assert.equal(h.state.result.value.total,0);assert.equal(h.state.error.value,'')
  }finally{h.close()}
})
for(const invalid of ['rows','counts','id'])test(`invalid result ${invalid} is never cached`,async()=>{
  const result=done();if(invalid==='rows')result.result.rows=null;if(invalid==='counts')result.result.total=3;if(invalid==='id')result.task_id='different'
  const h=mount({fetchTask:async()=>result})
  try{await h.state.onScan();assert.equal(h.state.result.value,null);assert.ok(h.state.error.value);assert.equal(h.cache.size,0)}finally{h.close()}
})
test('storage denial preserves valid live results with an explicit notice',async()=>{
  const h=mount({storageError:true})
  try{await h.state.onScan();assert.equal(h.state.result.value.total,0);assert.match(h.state.cacheNotice.value,/浏览器空间/);assert.equal(h.state.error.value,'')}finally{h.close()}
})
