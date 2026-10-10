import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'
import { frozenRadarSnapshot } from '../src/radar-evidence.ts'
import { radarReviewQuery, readRadarReview } from '../src/radar-review.ts'
import { validateRadarArchiveSource, withRadarArchiveSource } from '../src/radar-archive.ts'
import { validateResearchSnapshot } from '../src/research-snapshot-validation.ts'
import { planArchiveRecompute, recomputedArchiveDraft } from '../src/archive-recompute.ts'

function fixture() {
  const fingerprint='b'.repeat(64),taskId='a'.repeat(32)
  const metadata={source:'MAC',actual_adjust:'QFQ',requested_adjust:'QFQ',bar_time:'end',category:'DAY',observed_at:'2026-09-30 16:00:00',last_closed_at:'2026-09-30 15:00:00',data_fingerprint:fingerprint}
  const bars=['2026-09-28','2026-09-29','2026-09-30'].map(date=>({datetime:`${date} 15:00:00`,period_end:`${date} 15:00:00`,is_closed:true,open:29.1,high:30,low:28,close:29.023456789,vol:123456.789,amount:998877.66554433}))
  const row={strategy_id:'one',strategy_name:'MA',strategy_label:'均线',kind:'single',strategy:'ma_cross',params:{fast:7,slow:31},symbol:'SZ:300450',category:'DAY',metadata,latest_signal:'BUY',signal_date:'2026-09-30 15:00:00',recent_signals:[{date:'2026-09-30 15:00:00',direction:'BUY'}],position:'holding',last_close:29.023456789,last_bar_date:'2026-09-30 15:00:00',error:null}
  const review=readRadarReview(radarReviewQuery(row,'QFQ',undefined,{taskId,rowIndex:2})).value
  const receipt={contract:'radar-evidence-v1',task_id:taskId,row_index:2,window_bars:1,row,metadata,execution_version:'old',current_execution_version:'new',storage:'memory',bars}
  const source=frozenRadarSnapshot(receipt,review).radarSource
  const capture={title:'先导智能',cutoff:bars[1].period_end,target:{kind:'stock',code:'300450',market:'SZ'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},charts:[{category:'DAY',metadata,bars:bars.slice(0,2),result:{code:'stock:SZ:300450',frequency:'day',bis:[],xds:[],zss:[],mmds:[],bcs:[]}}]}
  return {source,capture}
}

test('save keeps original full input separate from replay prefix, fully detached from live state',()=>{
  const {source,capture}=fixture(),copy=structuredClone(source)
  const saved=withRadarArchiveSource(capture,reactive(source))
  assert.equal(saved.charts[0].bars.length,2);assert.equal(saved.radarSource.receipt.bars.length,3)
  assert.deepEqual(saved.radarSource,copy)
  source.receipt.bars[2].close=999
  assert.deepEqual(saved.radarSource,copy)
  assert.equal(withRadarArchiveSource(capture,null),capture)
})

test('same-bar opposite signals remain distinct; source survives JSON import without task or network',()=>{
  const {source,capture}=fixture(),row=source.receipt.row
  row.recent_signals.unshift({...row.recent_signals[0],direction:'SELL'})
  const raw=JSON.parse(JSON.stringify({schema:1,...withRadarArchiveSource(capture,source)}))
  assert.equal(validateResearchSnapshot(raw).radarSource.receipt.row.recent_signals.length,2)
  assert.equal(validateRadarArchiveSource(reactive(source)),reactive(source))
})

test('recompute uses only saved chart prefix, keeps original scan signals and version unchanged',()=>{
  const {source,capture}=fixture()
  const record={id:'00000000-0000-4000-8000-000000000001',kind:'chart',name:'复核',note:'',digest:'c'.repeat(64),revision:1,state:'active',size_bytes:100,created_at:'2026-10-10T00:00:00Z',updated_at:'2026-10-10T00:00:00Z',deleted_at:null,provenance:'client_archive_not_server_verified',payload:{schema:1,...withRadarArchiveSource(capture,source)}}
  const before=structuredClone(record),plan=planArchiveRecompute(record),job=plan.jobs[0]
  assert.equal(job.request.chart.bars.length,2)
  assert.equal(job.request.chart.radarSource,undefined)
  const response={contract:'archive-recompute-v1',kind:'chart',request_id:'test',input_digest:'d'.repeat(64),execution_version:'research-execution-v1:'+'e'.repeat(64),scope:'structure_and_macd_current_defaults',parameters:{},result:structuredClone(capture.charts[0].result),source:'client_supplied_archived_bars_not_market_verified',historical_data_vintage:false}
  const draft=recomputedArchiveDraft(record,plan,[response],'2026-10-10T00:00:00Z')
  assert.deepEqual(draft.payload.radarSource,source)
  assert.deepEqual(record,before)
})

for(const [name,mutate] of [
  ['wrong target',v=>v.capture.target.code='300750'],['board target',v=>v.capture.target.kind='board'],
  ['wrong market',v=>v.capture.target.market='SH'],['reference',v=>v.source.receipt.task_id='c'.repeat(32)],
  ['invalid date type',v=>v.source.review.signalDate=null],['noncanonical cutoff',v=>v.source.review.asOf='2026-09-30T15:00:00'],
  ['row summary',v=>v.source.receipt.row.last_close=999],['row last date',v=>v.source.receipt.row.last_bar_date='2026-09-29'],
  ['outside signal window',v=>v.source.receipt.row.recent_signals.unshift({date:'2026-09-28',direction:'SELL'})],
  ['row source',v=>v.source.receipt.row.metadata.data_fingerprint='c'.repeat(64)],
  ['row requested adjust',v=>v.source.receipt.row.metadata.requested_adjust='HFQ'],
  ['row quality',v=>v.source.receipt.row.metadata.quality={status:'error',errors:['bad']}],
  ['open candle',v=>v.source.receipt.bars[0].is_closed=false],['unsupported storage',v=>v.source.receipt.storage='missing'],
])test(`reject ${name} before saving; never silently drop invalid lineage`,()=>{
  const v=fixture();mutate(v)
  assert.throws(()=>withRadarArchiveSource(v.capture,v.source))
  assert.throws(()=>validateResearchSnapshot({schema:1,...v.capture,radarSource:v.source}))
})

test('legacy snapshot without original input still opens without invented source',()=>{
  const {capture}=fixture()
  capture.charts[0].metadata.original_task={task_id:'a'.repeat(32),row_index:2}
  assert.equal(validateResearchSnapshot({schema:1,...capture}).radarSource,undefined)
})
