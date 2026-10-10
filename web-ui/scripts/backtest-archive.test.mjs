import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import * as vue from 'vue'
import * as pinia from 'pinia'
import * as tasks from '../src/task-execution.ts'
import * as research from '../src/research-input.ts'
import {validateBacktestArchive,detachBacktest} from '../src/backtest-archive.ts'
import {prepareArchiveImport} from '../src/archive-import.ts'
import {planArchiveRecompute,recomputedArchiveDraft} from '../src/archive-recompute.ts'

const copy=v=>JSON.parse(JSON.stringify(v))
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
function fixture(){
  const bars=[1,2].map(day=>({datetime:`2026-09-0${day} 15:00:00`,open:10,high:11,low:9,close:10,vol:100,amount:1000}))
  const metrics='total_return annual_return max_drawdown max_dd_duration sharpe sortino calmar total_trades win_trades lose_trades rejected_trades win_rate profit_factor avg_win avg_loss max_win max_loss avg_holding_days volatility'.split(' ')
  return {format:'backtest-research-v1',title:'QA 原回测',savedAt:'2026-10-10T00:00:00Z',request:{symbol:'SZ:300450',category:'DAY',adjust:'QFQ',strategy:'ma_cross',params:{fast:7,slow:31},cash:100000.25,commission:.0003,min_commission:5.25,stamp_tax:.001,slippage:.0002,execution:'next_open',start_date:'2026-09-01',end_date:'2026-09-02',ohlcv:bars},metadata:{category:'DAY',actual_adjust:'QFQ',requested_adjust:'QFQ'},result:{performance:{...Object.fromEntries(metrics.map(k=>[k,0])),sharpe:null},config:{future_version:'unknown'},positions:[{datetime:bars[0].datetime,size:1}],trades:[{datetime:bars[1].datetime,direction:'BUY',size:100,price:10.123456789,commission:5.25,slippage:.1234,pnl:0,rejected:false}],equity_curve:bars.map(b=>({datetime:b.datetime,cash:100000.25,position_value:0,total:100000.25,drawdown:0,drawdown_pct:0})),unknown_original:{precision:.000000123456789}}}
}
test('full backtest file and cloud envelope retain all fields; no implicit Chanlun recompute',()=>{
  const original=fixture(),payload=validateBacktestArchive(vue.reactive(original)),saved=detachBacktest(payload)
  assert.deepEqual(saved,original);assert.equal(prepareArchiveImport(saved,'original.json').draft.kind,'backtest')
  const record={id:'00000000-0000-4000-8000-000000000001',kind:'backtest',name:'原档',note:'',revision:1,state:'active',digest:'a'.repeat(64),size_bytes:100,created_at:original.savedAt,updated_at:original.savedAt,deleted_at:null,provenance:'client_archive_not_server_verified',payload:saved}
  assert.deepEqual(prepareArchiveImport(record,'cloud.json').draft.payload,original)
  assert.throws(()=>planArchiveRecompute(record),/不调用缠论重算/)
  assert.throws(()=>recomputedArchiveDraft(record,{},[],original.savedAt),/不能写入缠论重算/)
  saved.request.ohlcv[0].close=11;assert.equal(original.request.ohlcv[0].close,10)
})
for(const [name,mutate] of [
  ['cash',p=>p.request.cash=true],['params',p=>p.request.params=[]],['adjust',p=>p.metadata.actual_adjust='HFQ'],['null lineage',p=>p.radarSource=null],
  ['net value',p=>p.result.equity_curve[0].total=null],['future trade',p=>p.result.trades[0].datetime='2030-01-01 15:00:00'],
  ['duplicate date',p=>p.result.equity_curve.push(p.result.equity_curve[0])],['missing metrics',p=>delete p.result.performance.sharpe],
  ['nested infinity',p=>p.result.unknown_original.precision=Infinity],['coerced rejected',p=>p.result.trades[0].rejected='false'],
])test(`invalid ${name} cannot become a readable archive`,()=>{const p=fixture();mutate(p);assert.throws(()=>validateBacktestArchive(p))})

function storeHarness(run){
  const identity=vue.ref({id:'alice'}),api={formatError:e=>e.message,runBacktest:run}
  const mocks={vue,pinia,'../research-input':research,'../task-execution':tasks,'../auth':{useAuth:()=>({currentUser:identity})},'../api':api}
  const source=readFileSync(new URL('../src/stores/backtest.ts',import.meta.url),'utf8')
  const output=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
  const mod={exports:{}}
  vm.runInNewContext(output,{module:mod,exports:mod.exports,require:p=>{if(!mocks[p])throw Error(p);return mocks[p]},setTimeout,clearTimeout})
  const p=pinia.createPinia();pinia.setActivePinia(p);const store=mod.exports.useBacktestStore()
  const data=fixture(),context={code:'300450',market:'SZ',category:'DAY',adjust:'QFQ',startDate:'2026-09-01',endDate:'2026-09-02'}
  store.setOhlcv(data.request.ohlcv,'QA',data.metadata,context)
  return {store,data,identity,close:()=>pinia.disposePinia(p)}
}
test('actual store freezes submitted input and result separately from later source mutation',async()=>{
  const wait=deferred();let sent,owner
  const h=storeHarness((req,identity)=>{sent=copy(req);owner=identity;return wait.promise})
  try{
    const running=h.store.run(h.data.request)
    assert.equal(owner,'alice')
    h.data.request.params.fast=99;h.data.request.ohlcv[0].close=11
    wait.resolve(h.data.result);await running
    assert.deepEqual(copy(h.store.completed.request),sent)
    h.data.result.trades[0].price=999;h.store.result.trades[0].price=777
    assert.equal(h.store.completed.result.trades[0].price,10.123456789)
    h.store.setOhlcv([], 'changed');assert.equal(h.store.result,null);assert.equal(h.store.completed,null)
  }finally{h.close()}
})
for(const change of ['owner','input','clear','failure'])test(`actual store rejects stale or failed ${change} run and clears prior archive`,async()=>{
  const wait=deferred(),h=storeHarness(()=>wait.promise)
  try{
    const running=h.store.run(h.data.request)
    if(change==='owner')h.identity.value={id:'bob'}
    if(change==='input')h.store.setOhlcv(h.data.request.ohlcv,'other',h.data.metadata,null)
    if(change==='clear')h.store.clearResult()
    if(change==='failure')wait.reject(Error('QA failure'));else wait.resolve(h.data.result)
    await running;assert.equal(h.store.completed,null);assert.equal(h.store.result,null);assert.equal(h.store.running,false)
  }finally{h.close()}
})
