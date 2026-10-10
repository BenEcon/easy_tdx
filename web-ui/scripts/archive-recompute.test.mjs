import test from 'node:test'
import assert from 'node:assert/strict'
import { planArchiveRecompute,checkRecomputeResult,compareArchiveValues,recomputedArchiveDraft,recomputeComparable } from '../src/archive-recompute.ts'
import { freezeChartIndicators } from '../src/frozen-chart-indicators.ts'

const bars=()=>[{datetime:'2026-10-09 00:00:00',open:1.123456789,close:2,high:3,low:1,vol:100,amount:200}]
const result=()=>({code:'stock:SZ:300750',frequency:'day',bis:[],xds:[],zss:[],bcs:[],mmds:[],custom:{value:1.234567891}})
const chart=()=>({schema:1,id:'local',owner:'alice',name:'原档',note:'原备注',title:'300750',cutoff:'2026-10-09 15:00:00',savedAt:'2026-10-09T08:00:00Z',frontendVersion:'old',ruleVersions:[20261004],target:{kind:'stock',market:'SZ',code:'300750'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},charts:[{category:'DAY',bars:bars(),metadata:{actual_adjust:'QFQ',observed_at:'2026-10-09 16:00:00',bar_time:'start'},result:result()}]})
const record=(payload=chart(),kind='chart')=>({id:'00000000-0000-4000-8000-000000000001',kind,name:'原档',note:'原备注',revision:1,state:'active',digest:'a'.repeat(64),size_bytes:100,created_at:'2026-10-09T08:00:00Z',updated_at:'2026-10-09T08:00:00Z',deleted_at:null,provenance:'client_archive_not_server_verified',payload})
const study=()=>({format:'chanlun-research-snapshot-v2',code:'300750',instrument:{kind:'stock',market:'SZ',code:'300750'},as_of:'2026-10-09 15:00:00',series:[{category:'DAY',snapshot:{bars:bars(),metadata:{actual_adjust:'QFQ',bar_time:'start'}}}],result:{rows:[{category:'DAY',error:'旧算法失败'},{category:'WEEK',error:'没有原始行情'}],parameters:{macd:[12,26,9],boll:[20,2],volume_multiple:3,squeeze_quantile:.3,ma_periods:[5,13],window_bars:30,window_start:null,window_end:null}}})
const response=(job,id='request')=>({contract:'archive-recompute-v1',request_id:id,kind:job.request.kind,input_digest:'c'.repeat(64),execution_version:'research-execution-v1:'+'d'.repeat(64),scope:job.request.kind==='chart'?'structure_and_macd_current_defaults':'study_saved_parameters_current_algorithm',parameters:{},result:job.request.kind==='chart'?result():{rows:[{category:'DAY',error:'本期仍无法计算'}]},source:'client_supplied_archived_bars_not_market_verified',historical_data_vintage:false})

test('chart plan freezes original data and uses original identity/window, not current selection',()=>{
  const original=record(),copy=structuredClone(original),plan=planArchiveRecompute(original)
  assert.deepEqual(original,copy)
  assert.equal(plan.jobs[0].request.chart.code,'stock:SZ:300750')
  assert.deepEqual(plan.jobs[0].request.chart.bars,original.payload.charts[0].bars)
  original.payload.charts[0].bars[0].close=99
  assert.equal(plan.jobs[0].request.chart.bars[0].close,2)
  assert.match(plan.warnings.join(' '),/不是原版本复现/)
})
test('missing volume/time/parameters and unsupported length never silently become a smaller/default study',()=>{
  for(const mutation of [v=>delete v.charts[0].bars[0].vol,v=>delete v.charts[0].bars[0].amount,v=>v.charts[0].bars[0].datetime+='Z']){
    const value=chart();mutation(value);assert.throws(()=>planArchiveRecompute(record(value)))
  }
  for(const mutation of [v=>delete v.result.parameters,v=>delete v.result.parameters.window_start,v=>delete v.series[0].snapshot.metadata.bar_time,v=>v.result.parameters.macd=[5,10,3],v=>delete v.instrument,v=>v.instrument.code='other',v=>v.result.parameters.volume_multiple='3',v=>v.result.parameters.window_bars=true,v=>v.as_of='2026-10-09']){
    const value=study();mutation(value);assert.throws(()=>planArchiveRecompute(record(value,'study')))
  }
  const value=chart();value.charts[0].bars=Array.from({length:801},(_,i)=>({...bars()[0],datetime:new Date(Date.UTC(2020,0,1+i)).toISOString().slice(0,10)+' 00:00:00'}))
  assert.throws(()=>planArchiveRecompute(record(value)),/800 根/)
})
test('study plan preserves actual research settings and saved time labels',()=>{
  const plan=planArchiveRecompute(record(study(),'study')),request=plan.jobs[0].request.study
  assert.equal(request.volume_multiple,3);assert.equal(request.window_bars,30)
  assert.deepEqual(request.ma_periods,[5,13]);assert.equal(request.series[0].bar_time,'start')
  assert.equal(request.series.length,1)
})
test('saved structural settings survive chart and study archive replay; mismatch is rejected',()=>{
  const settings={bi_type:'old',zs_min_lines:5},payload=chart()
  payload.charts[0].result.structure_settings=settings
  const job=planArchiveRecompute(record(payload)).jobs[0]
  assert.deepEqual(job.request.chart.structure_settings,settings)
  const returned=response(job)
  returned.scope='structure_and_macd_saved_settings'
  returned.result.structure_settings=settings
  assert.doesNotThrow(()=>checkRecomputeResult(returned,job,'request'))
  returned.result.structure_settings={bi_type:'new',zs_min_lines:3}
  assert.throws(()=>checkRecomputeResult(returned,job,'request'),/结构设置/)
  const s=study();s.result.parameters.structure_settings=settings
  assert.deepEqual(planArchiveRecompute(record(s,'study')).jobs[0].request.study.structure_settings,settings)
  payload.charts[0].result.structure_settings={bi_type:'unknown',zs_min_lines:5}
  assert.throws(()=>planArchiveRecompute(record(payload)),/结构计算设置/)
})
test('unrounded path diff distinguishes null, missing, structure, empty arrays, and ordering',()=>{
  const before={p:1.234567891,x:null,empty:[],a:[1,2]},after={p:1.234567892,y:null,empty:{},a:[2,1,3]}
  const diff=compareArchiveValues(before,after),map=new Map(diff.map(row=>[row.path,row]))
  assert.equal(map.get('$["p"]').after,1.234567892)
  assert.equal(map.get('$["x"]').afterPresent,false)
  assert.equal(map.get('$["y"]').beforePresent,false)
  assert.deepEqual(map.get('$["empty"]').before,[])
  assert.ok(map.has('$["a"].length'));assert.ok(map.has('$["a"][0]'))
  assert.deepEqual(compareArchiveValues(before,structuredClone(before)),[])
})
test('response must match request, instrument, version, scope and period identities',()=>{
  const job=planArchiveRecompute(record()).jobs[0],valid=response(job)
  assert.deepEqual(checkRecomputeResult(valid,job,'request'),valid)
  for(const mutation of [v=>v.request_id='other',v=>v.execution_version='current',v=>v.kind='study',v=>v.result.code='wrong',v=>delete v.input_digest,v=>v.scope='unknown']){
    const invalid=structuredClone(valid);mutation(invalid);assert.throws(()=>checkRecomputeResult(invalid,job,'request'))
  }
  const other=planArchiveRecompute(record(study(),'study')).jobs[0],next=response(other);next.result.rows=[]
  assert.throws(()=>checkRecomputeResult(next,other,'request'),/周期/)
})
test('new archive retains original bars/lineage but never relabels frozen old indicators as recomputed',()=>{
  const original=record(),copy=structuredClone(original),plan=planArchiveRecompute(original),values=plan.jobs.map(job=>response(job))
  plan.draft.payload.charts[0].frozenIndicators={old:'never inherit'}
  const draft=recomputedArchiveDraft(original,plan,values,'2026-10-10T00:00:00Z')
  assert.deepEqual(original,copy);assert.deepEqual(draft.payload.charts[0].bars,original.payload.charts[0].bars)
  assert.equal(draft.payload.charts[0].frozenIndicators,undefined)
  assert.deepEqual(draft.payload.ruleVersions,[])
  assert.equal(draft.payload.recomputation.source_archive.digest,original.digest)
  assert.equal(draft.payload.recomputation.runs[0].execution_version,values[0].execution_version)
  assert.throws(()=>recomputedArchiveDraft(original,plan,[],'now'),/未全部完成/)
})
test('study without saved input retains an explicit uncomputed row, never pretends all periods succeeded',()=>{
  const original=record(study(),'study'),plan=planArchiveRecompute(original),draft=recomputedArchiveDraft(original,plan,[response(plan.jobs[0])],'2026-10-10T00:00:00Z')
  assert.equal(draft.payload.result.rows.length,2)
  assert.match(draft.payload.result.rows[1].error,/未重算/)
  assert.equal(original.payload.result.rows[1].error,'没有原始行情')
})

test('complete indicator recompute preserves saved settings, checks response and saves only new values',()=>{
  const original=record()
  original.payload.charts[0].frozenIndicators=freezeChartIndicators(bars(),[5,17],[5],[{type:'rsi',params:{N:6},rows:[{RSI:0}]}])
  const copy=structuredClone(original),plan=planArchiveRecompute(original),job=plan.jobs[0]
  assert.deepEqual(job.request.chart_indicators,{averages:[{period:5,enabled:true},{period:17,enabled:false}],indicators:[{type:'rsi',params:{N:6}}]})
  const raw={...response(job),contract:'archive-recompute-v2',scope:'structure_macd_and_saved_chart_indicators',indicator_data:{averages:[{period:5,enabled:true,values:[null]},{period:17,enabled:false,values:[null]}],indicators:[{type:'rsi',params:{N:6},rows:[{RSI:null}]}]}}
  const checked=checkRecomputeResult(raw,job,'request'),diff=compareArchiveValues(job.before,recomputeComparable(checked))
  assert.ok(diff.some(row=>row.path==='$["frozenIndicators"]["indicators"][0]["series"][0]["values"][0]'&&row.before===0&&row.after===null))
  const saved=recomputedArchiveDraft(original,plan,[checked],'2026-10-10T00:00:00Z')
  assert.throws(()=>recomputedArchiveDraft(original,plan,[raw],'2026-10-10T00:00:00Z'),/指标未全部重算/)
  assert.deepEqual(saved.payload.charts[0].frozenIndicators.indicators[0].series[0].values,[null])
  assert.deepEqual(saved.payload.recomputation.runs[0].chart_indicator_parameters,job.request.chart_indicators)
  assert.equal(saved.payload.recomputation.runs[0].indicator_data,undefined)
  assert.deepEqual(original,copy)
  for(const mutate of [v=>delete v.indicator_data,v=>v.indicator_data.indicators[0].params.N=24,v=>v.indicator_data.indicators[0].rows=[],v=>v.indicator_data.indicators[0].rows[0]={RSI:'0'},v=>v.indicator_data.indicators[0].rows[0]={},v=>v.indicator_data.averages[0].period=6,v=>v.indicator_data.averages[0].values=[NaN]]){
    const bad=structuredClone(raw);mutate(bad);assert.throws(()=>checkRecomputeResult(bad,job,'request'))
  }
})

test('missing or unknown saved indicator parameters cannot borrow current defaults',()=>{
  for(const mutate of [v=>v.indicators[0].params={},v=>v.indicators[0].type='unknown',v=>v.indicators[0].series[0].name='other']){
    const original=record(),frozen=freezeChartIndicators(bars(),[],[],[{type:'rsi',params:{N:6},rows:[{RSI:1}]}]);mutate(frozen)
    original.payload.charts[0].frozenIndicators=frozen
    assert.throws(()=>planArchiveRecompute(original))
  }
})
