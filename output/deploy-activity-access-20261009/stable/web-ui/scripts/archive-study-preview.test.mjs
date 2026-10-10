import test from 'node:test'
import assert from 'node:assert/strict'
import { archiveStudyPreview,studyOverviewIssue } from '../src/archive-study-preview.ts'
import { periodOverviewCells } from '../src/period-overview.ts'

const valid=()=>({category:'DAY',price:10.123456789,axis:'零轴下方',histogram:'绿柱',volume_ratio:0,
  pairs:Object.fromEntries(['ma','volume','macd'].map(key=>[key,{fast:0,slow:null,description:key}])),
  ma_research:{bull:{to:null},bear:{to:20}},direction_observation:{strict:null,description:'未成笔',known_date:null},
  divergences:[{kind:'macd',date:'2026-09-11',direction:'down',status:'candidate',confirmed_date:null}],
  observations:['原版说明'],warmup_warning:false,excluded_bars:0,window:{start:'2026-09-01',end:'2026-10-09',count:20,truncated:false}})

test('original valid study rows retain precision, unknown fields, true zero and no recomputation',t=>{
  t.mock.method(globalThis,'fetch',()=>{throw Error('unexpected network')})
  const row={...valid(),future:{untouched:true}},payload={result:{rows:[row,{category:'WEEK',error:'原始取数失败'}]}}
  const before=JSON.stringify(payload),preview=archiveStudyPreview(payload)
  assert.equal(preview.rows[0],row);assert.equal(preview.entries[0].raw,row)
  assert.equal(preview.rows[0].price,10.123456789)
  assert.match(periodOverviewCells(preview.rows[0])[1].join(' '),/0.00/)
  assert.equal(preview.rows[1].error,'原始取数失败');assert.equal(JSON.stringify(payload),before)
})

test('invalid nested fields become explicit per-period errors, not silently missing rows',()=>{
  for(const mutate of [r=>r.price='10',r=>r.volume_ratio=Infinity,r=>r.axis={},r=>r.pairs.macd.fast='0',r=>r.pairs.ma=null,
    r=>r.ma_research.bull.to='5',r=>r.direction_observation.strict={},r=>r.direction_observation.known_date='2026-02-30',
    r=>r.divergences[0].date={},r=>r.divergences[0].direction=['down'],r=>r.divergences[0].status=[],r=>r.observations=[{}],r=>r.window=null,
    r=>r.window.count=-1,r=>r.window.end='2020-01-01',r=>r.warmup_warning='false',r=>r.excluded_bars=NaN,r=>r.error='']){
    const row=valid();mutate(row);assert.notEqual(studyOverviewIssue(row),null)
    const preview=archiveStudyPreview({result:{rows:[row]}})
    assert.equal(preview.rows.length,1);assert.match(preview.rows[0].error,/原档无法完整展示/)
    assert.equal(preview.entries[0].raw,row);assert.notEqual(preview.rows[0],row)
  }
})

test('strict pen fields reject coercion and preserve historical source errors without reading their invalid nested fields',()=>{
  const row=valid()
  row.direction_observation.strict={direction:'up',locked:true,start_date:'2026-09-01',end_date:'2026-09-11',start_price:10,end_price:12}
  assert.equal(studyOverviewIssue(row),null)
  row.direction_observation.strict.direction=['up']
  assert.equal(studyOverviewIssue(row),'direction_observation.strict')
  const sourceError={category:'DAY',error:'原始失败',last_closed_at:{invalid:true},direction_observation:42}
  const preview=archiveStudyPreview({result:{rows:[sourceError]}})
  assert.equal(preview.entries[0].raw,sourceError)
  assert.deepEqual(preview.rows,[{category:'DAY',error:'原始失败'}])
})

test('duplicates are not cherry-picked and malformed or future rows remain in original-record entries',()=>{
  const row=valid(),rows=[row,{...row,price:900},null,42,{category:'FUTURE',opaque:'keep'}]
  const preview=archiveStudyPreview({result:{rows}})
  assert.equal(preview.rows.length,1);assert.match(preview.rows[0].error,/重复记录/)
  assert.equal(preview.entries.length,rows.length)
  assert.deepEqual(preview.entries.map(entry=>entry.raw),rows)
  assert.ok(preview.entries.every(entry=>entry.problem))
  assert.equal(archiveStudyPreview({result:{rows:{}}}),null)
})
