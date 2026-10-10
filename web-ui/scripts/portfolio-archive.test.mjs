import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import {parse,compileScript} from '@vue/compiler-sfc'
import ts from 'typescript'
import * as vue from 'vue'
import * as portfolio from '../src/portfolio-archive.ts'
import * as backtest from '../src/backtest-archive.ts'
import {prepareArchiveImport} from '../src/archive-import.ts'
import {planArchiveRecompute,recomputedArchiveDraft} from '../src/archive-recompute.ts'

// Fast client lifecycle fixtures. Real-engine cross-language acceptance runs
// separately so npm tests remain independent of a local Python installation.
function fixture(kind){
  const shared={cash:200000.25,commission:.0003,min_commission:5.25,stamp_tax:.001,slippage:.0002,execution:'next_open',adjust:'QFQ'}
  const stocks=['SZ:300450','SH:600699'],base={strategy:'ma_cross',params:{fast:7,slow:31},category:'DAY',start_date:null,end_date:null}
  const request=kind==='portfolio'?{...shared,...base,stocks}:{...shared,items:stocks.map((symbol,i)=>({...base,symbol,strategy_label:`策略${i}`}))}
  const metrics='total_return annual_return max_drawdown max_dd_duration sharpe sortino calmar total_trades win_trades lose_trades rejected_trades win_rate profit_factor avg_win avg_loss max_win max_loss avg_holding_days volatility'.split(' ')
  const performance={...Object.fromEntries(metrics.map(k=>[k,0])),sharpe:null}
  const members=stocks.map((symbol,index)=>({index,symbol,key:kind==='portfolio'?symbol.replace(':',''):`策略${index}@${symbol}`,category:'DAY',metadata:{category:'DAY',actual_adjust:'QFQ',requested_adjust:'QFQ'},bars:[1,2].map(day=>({datetime:`2026-09-0${day} 15:00:00`,open:10,high:11,low:9,close:10,vol:100,amount:1000}))}))
  const individual_results=Object.fromEntries(members.map(m=>[m.key,{performance,config:{},positions:[],trades:[],equity_curve:m.bars.map(b=>({datetime:b.datetime,cash:100000.125,position_value:0,total:100000.125,drawdown:0,drawdown_pct:0}))}]))
  const result={individual_results,equity_allocation:Object.fromEntries(members.map(m=>[m.key,.5])),total_performance:{...performance,total_stocks:2,total_cash:shared.cash},combined_equity:members[0].bars.map(b=>({datetime:b.datetime,total:shared.cash,drawdown:0,drawdown_pct:0})),data_provenance:{request,datasets:members.map(m=>({label:m.key,symbol:m.symbol,bar_count:m.bars.length,metadata:m.metadata}))},future:{precision:.0000000123456789}}
  return {format:'portfolio-research-v1',title:'完整组合原档',savedAt:'2026-10-10T04:00:00Z',receipt:{contract:'portfolio-evidence-v1',kind,task_id:'original-task',execution_version:'original-version',current_execution_version:'current-version',storage:'memory',request,members,result}}
}
const originals=['portfolio','multi_strategy'].map(fixture)
const copy=backtest.detachBacktest
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r});return{promise,resolve}}
const file=new URL('../src/components/PortfolioArchiveTools.vue',import.meta.url)
const {descriptor}=parse(readFileSync(file,'utf8'),{filename:file.pathname})
const compiled=ts.transpileModule(compileScript(descriptor,{id:'portfolio-tools'}).content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
function mount(original,respond=async()=>new Response(JSON.stringify(original.receipt))){
  const owner=vue.ref({id:'alice'}),stops=[],calls=[]
  const props=vue.reactive({kind:original.receipt.kind,taskId:original.receipt.task_id,request:copy(original.receipt.request),result:copy(original.receipt.result),busy:false})
  const mocks={vue:{...vue,onBeforeUnmount:f=>stops.push(f)},'../auth':{useAuth:()=>({currentUser:owner})},'../portfolio-archive':portfolio,'../backtest-archive':backtest}
  const mod={exports:{}}
  vm.runInNewContext(compiled,{module:mod,exports:mod.exports,require:p=>mocks[p]??(p.endsWith('.vue')?{}:(()=>{throw Error(p)})()),AbortController,fetch:(...args)=>{calls.push(args);return respond(...args)}},{filename:file.pathname})
  const scope=vue.effectScope(),state=scope.run(()=>mod.exports.default.setup(props,{expose(){}}))
  return{owner,props,state,calls,close:()=>{stops.forEach(f=>f());scope.stop()}}
}
for(const original of originals){
  const kind=original.receipt.kind
  test(`${kind}: all original values survive import and cloud envelope; no Chanlun recompute`,()=>{
    assert.deepEqual(portfolio.validatePortfolioArchive(copy(original)),original)
    const imported=prepareArchiveImport(original,'full.json')
    assert.equal(imported.draft.kind,'portfolio');assert.deepEqual(imported.draft.payload,original)
    const record={id:'00000000-0000-4000-8000-000000000001',kind:'portfolio',name:'原档',note:'',revision:1,state:'active',digest:'a'.repeat(64),size_bytes:100,created_at:original.savedAt,updated_at:original.savedAt,deleted_at:null,provenance:'client_archive_not_server_verified',payload:original}
    assert.deepEqual(prepareArchiveImport(record,'cloud.json').draft.payload,original)
    assert.throws(()=>planArchiveRecompute(record),/不调用缠论重算/)
    assert.throws(()=>recomputedArchiveDraft(record,{},[],original.savedAt),/不能写入缠论重算/)
  })
  test(`${kind}: actual component fetches only explicitly, binds owner/request/result and freezes capture`,async()=>{
    const h=mount(original)
    try{
      assert.equal(h.calls.length,0);assert.throws(()=>h.state.capture())
      await h.state.prepare();assert.equal(h.state.error.value,'')
      const saved=h.state.capture();assert.deepEqual(saved.payload.receipt,original.receipt)
      saved.payload.receipt.members[0].bars[0].close=999
      assert.notEqual(h.state.capture().payload.receipt.members[0].bars[0].close,999)
      assert.equal(h.calls[0][1].headers['X-Task-Owner'],'alice');assert.equal(h.calls[0][1].headers['X-Query-Origin'],'system')
      h.owner.value={id:'bob'};assert.equal(h.state.prepared.value,null);assert.throws(()=>h.state.capture())
    }finally{h.close()}
  })
  for(const change of ['owner','request','task','result','busy','unmount'])test(`${kind}: late receipt discarded after ${change}`,async()=>{
    const wait=deferred(),h=mount(original,()=>wait.promise)
    try{
      const pending=h.state.prepare()
      if(change==='owner')h.owner.value={id:'bob'}
      if(change==='task')h.props.taskId='new-task'
      if(change==='request')h.props.request={...h.props.request,cash:999}
      if(change==='result')h.props.result={...h.props.result,total_performance:{}}
      if(change==='busy')h.props.busy=true
      if(change==='unmount')h.close()
      wait.resolve(new Response(JSON.stringify(original.receipt)));await pending
      assert.equal(h.state.prepared.value,null)
    }finally{h.close()}
  })
  for(const change of ['missing','allocation','metadata','date','precision','curve','request','trade'])test(`${kind}: invalid ${change} rejected`,()=>{
    const value=copy(original),r=value.receipt
    if(change==='missing')r.members.pop()
    if(change==='allocation')r.result.equity_allocation[r.members[0].key]=.4
    if(change==='metadata')r.members[0].metadata.actual_adjust='NONE'
    if(change==='date'){const item=kind==='portfolio'?r.request:r.request.items[0];item.start_date='';r.result.data_provenance.request=copy(r.request)}
    if(change==='precision')r.result.unknown=Infinity
    if(change==='curve')r.result.combined_equity[1].datetime=r.result.combined_equity[0].datetime
    if(change==='request')r.request.cash=true
    if(change==='trade')r.result.individual_results[r.members[0].key].trades.push({datetime:'2030-01-01 15:00:00'})
    assert.throws(()=>portfolio.validatePortfolioArchive(value))
  })
  test(`${kind}: unavailable or different task never falls back to fetching data`,async()=>{
    for(const response of [new Response(JSON.stringify({detail:'原任务已清理'}),{status:404}),new Response(JSON.stringify({...original.receipt,task_id:'other'}))]){
      const h=mount(original,async()=>response)
      try{await h.state.prepare();assert.ok(h.state.error.value);assert.equal(h.state.prepared.value,null);assert.equal(h.calls.length,1)}finally{h.close()}
    }
  })
}
test('normalized server defaults may extend but not alter submitted parameters',()=>{
  assert.equal(portfolio.portfolioRequestMatches({items:[{symbol:'SZ:300750'}]},{items:[{symbol:'SZ:300750',params:{}}],cash:100000}),true)
  assert.equal(portfolio.portfolioRequestMatches({items:[{symbol:'SZ:300750'}]},{items:[{symbol:'SZ:300450'}]}),false)
  assert.equal(portfolio.samePortfolioValue({a:1,b:2},{b:2,a:1}),true)
})
