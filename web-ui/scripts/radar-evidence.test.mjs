import test from 'node:test'
import assert from 'node:assert/strict'
import { frozenRadarSnapshot } from '../src/radar-evidence.ts'
import { fetchRadarSnapshot } from '../src/api.ts'
import { radarReviewQuery, readRadarReview, readRadarCache } from '../src/radar-review.ts'

const taskId='a'.repeat(32),fingerprint='b'.repeat(64)
const metadata={source:'MAC',actual_adjust:'QFQ',requested_adjust:'QFQ',category:'DAY',last_closed_at:'2026-09-30 15:00:00',data_fingerprint:fingerprint}
const row={strategy_id:'one',strategy_name:'MA',strategy_label:'均线',kind:'single',strategy:'ma_cross',params:{fast:7,slow:31},symbol:'SZ:300450',category:'DAY',metadata,latest_signal:'BUY',signal_date:'2026-09-30 15:00:00',recent_signals:[{date:'2026-09-30 15:00:00',direction:'BUY'}],position:'holding',last_close:29.023456789,last_bar_date:'2026-09-30 15:00:00',error:null}
const query=radarReviewQuery(row,'QFQ',undefined,{taskId,rowIndex:2})
const review=readRadarReview(query).value
const receipt=()=>({contract:'radar-evidence-v1',task_id:taskId,row_index:2,window_bars:5,row:structuredClone(row),metadata:structuredClone(metadata),execution_version:'original',current_execution_version:'original',storage:'persistent',bars:['2024-01-02','2026-09-30'].map(date=>({datetime:`${date}T15:00:00`,period_end:`${date}T15:00:00`,is_closed:true,open:29.1,high:30,low:28,close:29.023456789,vol:123456.789,amount:998877.66554433}))})

test('original task references round-trip and legacy references remain distinguishable',()=>{
  assert.deepEqual(review.evidence,{taskId,rowIndex:2})
  const legacy=radarReviewQuery(row,'QFQ')
  assert.equal(readRadarReview(legacy).value.evidence,undefined)
  for(const patch of [{scanTaskId:undefined},{scanTaskId:[taskId]},{scanTaskId:'../etc'},{scanRowIndex:undefined},{scanRowIndex:'02'},{scanRowIndex:'-1'},{scanRowIndex:'1000000'},{scanRowIndex:[]},{scanFingerprint:''}]){
    assert.equal(readRadarReview({...query,...patch}).value,null,JSON.stringify(patch))
  }
})

test('cache receipt must be a real ID string, never coerced or inherited from another owner',()=>{
  const cache={schema:'radar-cache-v2',owner:'alice',scannedAt:'now',windowBars:5,adjust:'QFQ',result:{rows:[row],total:1,buy_count:1,sell_count:0,error_count:0,elapsed:1,evidence_task_id:taskId}}
  assert.ok(readRadarCache(JSON.stringify(cache),'alice'))
  assert.equal(readRadarCache(JSON.stringify(cache),'bob'),null)
  for(const bad of [[taskId],null,12,{},'bad'])assert.equal(readRadarCache(JSON.stringify({...cache,result:{...cache.result,evidence_task_id:bad}}),'alice'),null)
})

test('all frozen bars and precision survive; changed code is disclosed, not represented as old execution',()=>{
  const source=receipt(),before=structuredClone(source)
  const snapshot=frozenRadarSnapshot(source,review)
  assert.deepEqual(snapshot.bars,source.bars)
  assert.equal(snapshot.metadata.original_task.compatible,true)
  assert.equal(snapshot.metadata.data_fingerprint,fingerprint)
  assert.deepEqual(source,before)
  source.current_execution_version='new'
  assert.equal(frozenRadarSnapshot(source,review).metadata.original_task.compatible,false)
  assert.match(frozenRadarSnapshot(source,review).metadata.consistency_note,/不声称原算法重放/)
})

for(const [name,mutate] of [
  ['task',r=>r.task_id='c'.repeat(32)],['row',r=>r.row_index=1],['market',r=>r.row.symbol='SH:300450'],
  ['symbol',r=>r.row.symbol=null],['params',r=>r.row.params=null],['strategy',r=>r.row.strategy='other'],
  ['fingerprint',r=>r.metadata.data_fingerprint='c'.repeat(64)],['adjust',r=>r.metadata.actual_adjust='NONE'],
  ['signal',r=>r.row.recent_signals=[]],['malformed signals',r=>r.row.recent_signals={}],['row error',r=>r.row.error='failed'],
  ['storage',r=>r.storage='unknown'],['version',r=>r.execution_version=null],['missing bars',r=>r.bars=[]],
  ['null bar',r=>r.bars[0]=null],['order',r=>r.bars.reverse()],['open bar',r=>r.bars[0].is_closed=false],
  ['future',r=>r.bars[1].period_end='2026-10-10'],['negative duration',r=>r.bars[1].period_end='2026-09-29'],
  ['missing cutoff',r=>r.metadata.last_closed_at=null],['number string',r=>r.bars[0].close='29'],
  ['NaN',r=>r.bars[0].close=NaN],['bad low',r=>r.bars[0].low=31],['negative volume',r=>r.bars[0].vol=-1],
])test(`invalid original receipt ${name} stops instead of substituting live data`,()=>{
  const raw=receipt();mutate(raw);assert.throws(()=>frozenRadarSnapshot(raw,review))
})

test('API sends owner and abort signal with no-store; unavailable receipt never calls a live feed',async()=>{
  const original=globalThis.fetch,calls=[],controller=new AbortController()
  globalThis.fetch=async(url,init)=>{calls.push({url:String(url),init});return new Response(JSON.stringify(receipt()))}
  try{
    const got=await fetchRadarSnapshot(review,'alice',controller.signal)
    assert.equal(got.bars[0].close,29.023456789)
    assert.match(calls[0].url,new RegExp(`/tasks/${taskId}/scan-evidence/2$`))
    assert.equal(new Headers(calls[0].init.headers).get('X-Task-Owner'),'alice')
    assert.equal(calls[0].init.signal,controller.signal);assert.equal(calls[0].init.cache,'no-store')
    await assert.rejects(fetchRadarSnapshot(review,''));assert.equal(calls.length,1)
    globalThis.fetch=async(url)=>{calls.push({url:String(url)});return new Response(JSON.stringify({detail:'原任务已清理'}),{status:404})}
    await assert.rejects(fetchRadarSnapshot(review,'alice'),/原任务已清理/)
    assert.equal(calls.length,2);assert.ok(calls.every(c=>c.url.includes('/scan-evidence/')))
  }finally{globalThis.fetch=original}
})
