import test from 'node:test'
import assert from 'node:assert/strict'
import { compareArchiveEvents } from '../src/archive-event-comparison.ts'

const event = (type='macd') => ({type,bc:true,direction:'down',curr_date:'2026-07-24 14:00',prev_date:'2026-07-20 13:00',status:'candidate',detected_date:'2026-07-24 14:15',
  intervals:{original_a_start:'2026-07-20 09:45',a_start:'2026-07-20 10:00',b_start:'2026-07-22 09:45',c_start:'2026-07-24 09:45'},evidence:{area:1.234567891,price:19.18}})
const diagnostic=(family='standard')=>({family,direction:'down',status:'blocked',first_candidate_index:null,closed:true,dates:{c_start:'2026-07-24 09:45',b_start:'2026-07-22 09:45'},checks:[{gate:'price',passed:false,values:{price:19.18}},{gate:'area',passed:true,values:{area:1.234567891}}],comparisons:[{mode:'full_a',passed:false},{mode:'equal_price',passed:true}],rejections:[{from_date:'2026-07-24 10:00',through_date:'2026-07-24 10:15',gates:['price','dif']} ]})
const result=()=>({code:'stock:SZ:300750',frequency:'day',bcs:[event(),event('macd_wave'),event('macd_wave_nonstandard'),event('macd_wave_special')],mmds:[{type:'3buy',date:'2026-07-24 14:00',source:'confirmed_segment_base_v1',confirmed_date:'2026-07-25 14:30',evidence:{return_segment:4}}],wave_diagnostics:[diagnostic(),diagnostic('special'),diagnostic('double')]})

test('event lists and evidence-set reordering never imply new or changed signals; originals remain intact',()=>{
  const a=result(),b=structuredClone(a),copy=structuredClone(a)
  b.bcs.reverse();b.wave_diagnostics.reverse()
  for(const row of b.wave_diagnostics){row.checks.reverse();row.comparisons.reverse();row.rejections[0].gates.reverse()}
  const report=compareArchiveEvents({result:a,frozenIndicators:{}},b)
  assert.deepEqual(report.counts,{added:0,removed:0,changed:0,same:8,unresolved:0})
  assert.deepEqual(a,copy)
  assert.equal(report.rows.find(row=>row.label.startsWith('局部双线')&&row.collection==='bcs').after[0].path,'$["bcs"][3]')
})
test('state, lifecycle times and unrounded evidence are classified separately on the same identity',()=>{
  const a=result(),b=structuredClone(a)
  b.bcs[0].status='confirmed';b.bcs[0].confirmed_date='2026-07-27 09:45';b.bcs[0].evidence.area+=1e-10
  const report=compareArchiveEvents(a,b),row=report.rows.find(row=>row.change==='changed')
  assert.deepEqual(row.facets,['state','timing','evidence']);assert.equal(report.counts.changed,1)
  assert.equal(row.differences.find(d=>d.path==='$["evidence"]["area"]').after,b.bcs[0].evidence.area)
  assert.equal(row.differences.find(d=>d.path==='$["confirmed_date"]').beforePresent,false)
})
test('same date across families and sides remains independent; true event additions/removals are distinct',()=>{
  const a=result(),b=structuredClone(a);b.bcs.shift();b.bcs.push({...event(),direction:'up'})
  const report=compareArchiveEvents(a,b)
  assert.equal(report.counts.removed,1);assert.equal(report.counts.added,1);assert.equal(report.counts.same,7)
})
test('duplicate identities preserve all records and are never paired arbitrarily',()=>{
  const a=result(),b=structuredClone(a);b.bcs.push({...event(),status:'confirmed'})
  const report=compareArchiveEvents(a,b),row=report.rows.find(r=>r.change==='unresolved')
  assert.equal(report.counts.unresolved,1);assert.equal(report.counts.changed,0)
  assert.equal(row.before.length,1);assert.equal(row.after.length,2);assert.match(row.reason,/多条/)
})
test('missing identity does not cause false removals or additions in its collection',()=>{
  const a=result(),b=structuredClone(a);delete a.bcs[0].prev_date
  const report=compareArchiveEvents(a,b)
  assert.equal(report.counts.added,0);assert.equal(report.counts.removed,0);assert.equal(report.counts.unresolved,2)
  assert.equal(report.counts.same,7)
})
test('missing source/list is unknown, not empty or proof of no events',()=>{
  const a=result(),b=structuredClone(a);delete a.wave_diagnostics;delete a.mmds[0].source
  const report=compareArchiveEvents(a,b)
  assert.equal(report.counts.added,0);assert.equal(report.counts.removed,0)
  assert.equal(report.coverage[2].before,null);assert.equal(report.coverage[2].comparable,false)
  assert.equal(report.rows.filter(row=>row.collection==='wave_diagnostics').length,3)
  assert.equal(report.counts.unresolved,5)
  const empty={...result(),bcs:[],mmds:[],wave_diagnostics:[]}
  assert.equal(compareArchiveEvents(empty,result()).counts.added,8)
})
test('never-candidate diagnostics match without A or reference, including special B-only records',()=>{
  const a=result(),b=structuredClone(a)
  b.wave_diagnostics[0].status='candidate';b.wave_diagnostics[0].first_candidate_index=19
  assert.equal(compareArchiveEvents(a,b).counts.changed,1)
  assert.equal(compareArchiveEvents(a,b).counts.unresolved,0)
})
test('A trimming changes evidence not identity; original wave anchors and reference changes distinguish bases',()=>{
  const a=result(),b=structuredClone(a);b.bcs[1].intervals.a_start='2026-07-20 10:15'
  assert.equal(compareArchiveEvents(a,b).counts.changed,1)
  b.bcs[1].intervals.original_a_start='2026-07-19 09:45'
  assert.equal(compareArchiveEvents(a,b).counts.changed,0)
  assert.equal(compareArchiveEvents(a,b).counts.added,1)
})
test('date normalization preserves intraday, microsecond and timezone distinctions',()=>{
  const a=result(),b=structuredClone(a);b.bcs[0].curr_date='2026-07-24T14:00:00.000'
  assert.equal(compareArchiveEvents(a,b).counts.added,0)
  assert.equal(compareArchiveEvents(a,b).counts.changed,1) // raw notation still disclosed
  for(const date of ['2026-07-24 14:01','2026-07-24','2026-07-24 14:00:00.000001','2026-07-24 14:00Z']){
    b.bcs[0].curr_date=date;assert.equal(compareArchiveEvents(a,b).counts.added,1,date)
  }
  b.bcs[0].curr_date='2026-02-30 14:00';assert.equal(compareArchiveEvents(a,b).counts.unresolved,2)
})
test('source differences and unknown fields/ordered evidence are retained',()=>{
  const a=result(),b=structuredClone(a);b.mmds[0].source='another_basis'
  assert.equal(compareArchiveEvents(a,b).counts.added,1)
  a.bcs[0].evidence.sequence=[1,2];b.bcs[0].evidence.sequence=[2,1];b.bcs[0].new_field=null
  const row=compareArchiveEvents(a,b).rows.find(row=>row.change==='changed')
  assert.ok(row.differences.some(d=>d.path.includes('sequence')))
  assert.ok(row.differences.some(d=>d.path.includes('new_field')&&d.beforePresent===false&&d.after===null))
})
test('different instruments, periods or study results are not matched',()=>{
  for(const b of [{...result(),code:'stock:SH:600000'},{...result(),frequency:'30min'},{rows:[]},{}]){
    const report=compareArchiveEvents(result(),b);assert.equal(report.applicable,false);assert.equal(report.rows.length,0)
  }
})
test('structure divergences are supported without inventing MACD wave anchors',()=>{
  const a=result();a.bcs=['bi','pz','qs'].map(type=>{const row=event(type);delete row.intervals;return row})
  assert.equal(compareArchiveEvents(a,structuredClone(a)).counts.same,7)
})
