import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import vm from 'node:vm'
import {parse,compileScript} from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as studyArchive from '../src/study-archive.ts'
import * as study from '../src/research-study.ts'
import * as market from '../src/market.ts'
import * as contract from '../src/market-data-contract.ts'
import * as target from '../src/chanlun-target.ts'
import * as overview from '../src/period-overview.ts'
import * as workspace from '../src/research-workspace.ts'
import * as origin from '../src/query-origin.ts'
import {prepareArchiveImport} from '../src/archive-import.ts'
import {planArchiveRecompute,recomputedArchiveDraft} from '../src/archive-recompute.ts'

const require=createRequire(import.meta.url),file=new URL('../src/components/MultiPeriodResearch.vue',import.meta.url)
const {descriptor}=parse(readFileSync(file,'utf8'),{filename:file.pathname})
const compiled=ts.transpileModule(compileScript(descriptor,{id:'study-lifecycle'}).content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
const row=category=>({category,error:'QA 引擎无足够行情'})
const snapshot=(category='DAY')=>({bars:[{datetime:'2026-09-29 15:00:00',period_end:'2026-09-29 15:00:00',is_closed:true,open:10,close:10,low:9,high:11,vol:100,amount:1000}],metadata:{source:'QA',requested_adjust:'QFQ',actual_adjust:'QFQ',category,bar_time:'end',observed_at:'2026-09-30 16:00:00',last_closed_at:'2026-09-29 15:00:00'}})
function radarSource(){
  const original=snapshot();original.bars.push({...original.bars[0],datetime:'2026-09-30 15:00:00',period_end:'2026-09-30 15:00:00'});original.metadata.last_closed_at='2026-09-30 15:00:00';original.metadata.data_fingerprint='b'.repeat(64)
  return {contract:'radar-archive-v1',review:{symbol:'300450',category:'DAY',adjust:'QFQ',asOf:'2026-09-30 15:00:00',signalDate:'',signal:'无指定信号',strategy:'ma_cross',name:'原策略',params:{fast:7,slow:31},fingerprint:'b'.repeat(64),evidence:{taskId:'a'.repeat(32),rowIndex:0}},receipt:{contract:'radar-evidence-v1',task_id:'a'.repeat(32),row_index:0,window_bars:1,execution_version:'old',current_execution_version:'new',storage:'memory',...original,row:{symbol:'SZ:300450',category:'DAY',strategy:'ma_cross',strategy_name:'原策略',params:{fast:7,slow:31},metadata:original.metadata,latest_signal:null,signal_date:null,recent_signals:[],position:'flat',last_close:10,last_bar_date:'2026-09-30 15:00:00'}}}
}
function mount({get=async(_target,category)=>snapshot(category),respond=async body=>({as_of:body.window_end??body.as_of,rows:body.series.map(s=>row(s.category)),parameters:{macd:[12,26,9],boll:[20,2],window_start:null,window_end:null,...body},conflicts:[],policy:'QA',rule_version:'qa'})}={}){
  const owner=vue.ref({id:'alice'}),stops=[],requests=[],gets=[]
  const mocks={vue:{...vue,onBeforeUnmount:f=>stops.push(f)},'../auth':{useAuth:()=>({currentUser:owner})},'../query-origin':origin,'../study-archive':studyArchive,'../research-study':study,'../market':market,'../market-data-contract':contract,'../chanlun-target':target,'../period-overview':overview,'../research-workspace':workspace,
    '../api':{formatError:e=>e.message,fetchResearchSnapshot:(...args)=>{gets.push(origin.queryIntentHeaders()['X-Query-Origin']);return get(...args)}}}
  const mod={exports:{}}
  vm.runInNewContext(compiled,{module:mod,exports:mod.exports,require:p=>mocks[p]??(p.endsWith('.vue')?{}:require(p)),AbortController,setTimeout:()=>1,clearTimeout(){},fetch:async(_url,init)=>{const body=JSON.parse(init.body);requests.push({body,headers:init.headers});return new Response(JSON.stringify(await respond(body))) }},{filename:file.pathname})
  const props=vue.reactive({code:'300450',target:{kind:'stock',market:'SZ',code:'300450'},adjust:'QFQ',asOf:'2026-09-30 15:00:00',primaryCategory:'DAY',primarySnapshot:snapshot(),maPeriods:[5,10],active:true,busy:false})
  const scope=vue.effectScope(),state=scope.run(()=>mod.exports.default.setup(props,{expose(){}}))
  return{state,props,owner,requests,gets,close:()=>{stops.forEach(f=>f());scope.stop()}}
}
const record=payload=>({id:'00000000-0000-4000-8000-000000000001',kind:'study',name:'原研究',note:'',revision:1,state:'active',digest:'a'.repeat(64),size_bytes:100,created_at:'2026-10-10T00:00:00Z',updated_at:'2026-10-10T00:00:00Z',deleted_at:null,provenance:'client_archive_not_server_verified',payload})

test('actual component captures every selected period and failure; automatic work stays system-origin',async()=>{
  const h=mount({get:async(_target,p)=>{throw Error(`${p} 无行情`)}})
  try{
    h.state.selected.value=['WEEK','DAY','MIN_5']
    await h.state.run()
    const saved=h.state.captureStudy()
    assert.deepEqual(saved.collection.selected_periods,['WEEK','DAY','MIN_5'])
    assert.equal(saved.series.length,1);assert.equal(saved.result.rows.length,3)
    assert.match(saved.result.rows[0].error,/WEEK 无行情/)
    assert.equal(saved.result.rows[0].failure_stage,'collection')
    assert.equal(h.requests[0].headers['X-Query-Origin'],'system')
    assert.deepEqual(h.gets,['system','system'])
    assert.equal(prepareArchiveImport(saved,'study.json').draft.kind,'study')
    saved.result.rows[0].error='mutated'
    assert.match(h.state.captureStudy().result.rows[0].error,/WEEK 无行情/)
    await h.state.run(true);assert.equal(h.requests[1].headers['X-Query-Origin'],'user')
    assert.deepEqual(h.gets,['system','system','user','user'])
  }finally{h.close()}
})

test('all collection failures are exportable reports, never empty success or recomputable invented bars',async()=>{
  const h=mount({get:async()=>{throw Error('节点不可用')}})
  try{
    h.state.selected.value=['WEEK','MIN_5'];await h.state.run(true)
    const saved=h.state.captureStudy()
    assert.equal(h.requests.length,0);assert.equal(saved.collection.execution,'not_started')
    assert.deepEqual(h.gets,['user','user'])
    assert.equal(saved.series.length,0);assert.equal(saved.result.rows.length,2)
    assert.match(saved.result.policy,/不生成结论/)
    assert.equal(prepareArchiveImport(saved,'failure.json').draft.kind,'study')
    assert.throws(()=>planArchiveRecompute(record(saved)),/全部取数失败/)
  }finally{h.close()}
})

test('missing response rows are retained as explicit errors; unexpected rows or cutoff cannot enter a saved result',async()=>{
  for(const bad of ['missing','extra','cutoff','transport']){
    const h=mount({respond:async body=>{
      if(bad==='transport')throw Error('连接中断')
      return {as_of:bad==='cutoff'?'2026-09-29 15:00:00':body.as_of,rows:bad==='extra'?[row('MONTH')]:[],parameters:{},policy:'QA',conflicts:[],rule_version:'qa'}
    }})
    try{
      h.state.selected.value=['DAY'];await h.state.run(true)
      const saved=h.state.captureStudy()
      assert.equal(saved.result.rows.length,1);assert.equal(saved.result.rows[0].category,'DAY')
      assert.match(saved.result.rows[0].error,bad==='missing'?/未返回本周期/:bad==='transport'?/连接中断/:/不一致|非请求周期/)
      assert.equal(saved.collection.execution,bad==='missing'?'completed':'failed')
    }finally{h.close()}
  }
})

for(const change of ['account','input','unmount'])test(`late study response cannot be saved after ${change}`,async()=>{
  const wait=deferred(),h=mount({respond:()=>wait.promise})
  try{
    h.state.selected.value=['DAY'];const pending=h.state.run(true)
    if(change==='account')h.owner.value={id:'bob'}
    if(change==='input')h.props.code='300750'
    if(change==='unmount')h.close()
    wait.resolve({as_of:'2026-09-30 15:00:00',rows:[row('DAY')]});await pending
    assert.equal(h.state.completed.value,null);assert.throws(()=>h.state.captureStudy())
  }finally{if(change!=='unmount')h.close()}
})

test('invalid collection coverage cannot silently omit a period during import',async()=>{
  const h=mount()
  try{
    h.state.selected.value=['DAY'];await h.state.run(true)
    const saved=h.state.captureStudy()
    for(const mutate of [v=>v.collection.selected_periods.push('WEEK'),v=>v.result.rows=[],v=>v.collection.execution='not_started',v=>v.collection.selected_periods=['DAY','DAY'],v=>v.collection.execution=['completed']]){
      const bad=structuredClone(saved);mutate(bad);assert.throws(()=>prepareArchiveImport(bad,'bad.json'))
    }
    const original=record(saved),plan=planArchiveRecompute(original)
    const response={execution_version:'same-version',result:{...saved.result,rows:[row('DAY')]}}
    const next=recomputedArchiveDraft(original,plan,[response],'2026-10-10T01:00:00Z')
    assert.equal(next.payload.collection.execution,'completed')
  }finally{h.close()}
})

test('actual study freezes independent radar lineage, preserves it through import and recompute, and refuses foreign source',async()=>{
  const h=mount()
  try{
    h.props.radarSource=radarSource();h.state.selected.value=['DAY'];await h.state.run(true)
    const saved=h.state.captureStudy()
    assert.equal(saved.series[0].snapshot.bars.length,1);assert.equal(saved.radarSource.receipt.bars.length,2)
    const imported=prepareArchiveImport(saved,'radar-study.json').draft
    assert.deepEqual(imported.payload.radarSource,saved.radarSource)
    const original=record(saved),plan=planArchiveRecompute(original)
    assert.equal(plan.jobs[0].request.study.series[0].bars.length,1)
    assert.equal(plan.jobs[0].request.study.radarSource,undefined)
    const next=recomputedArchiveDraft(original,plan,[{execution_version:'new',result:saved.result}],'2026-10-10T01:00:00Z')
    assert.deepEqual(next.payload.radarSource,saved.radarSource)
    h.props.radarSource.review.symbol='300750';await h.state.run(true)
    assert.throws(()=>h.state.captureStudy());assert.match(h.state.errors.value.join(' '),/不一致/)
    assert.equal(h.requests.length,1)
  }finally{h.close()}
})
