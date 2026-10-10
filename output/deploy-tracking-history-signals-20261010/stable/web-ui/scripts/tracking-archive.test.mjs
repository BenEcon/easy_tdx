import test from 'node:test'
import assert from 'node:assert/strict'
import {trackingArchiveDraft,validateTrackingArchive} from '../src/tracking-archive.ts'
import {createTrackingAutoSave} from '../src/tracking-autosave.ts'
import {prepareArchiveImport} from '../src/archive-import.ts'
const target={kind:'stock',market:'SZ',code:'300750',name:'宁德时代'}
const cutoff='2026-10-10 10:00:00'
const payload=()=>({format:'tracking-analysis-v2',group:{id:'g',name:'观察组',targets:[target]},revision:'r',periods:['DAY'],cutoff,finished_at:'2026-10-10T02:00:30Z',membership_observed_at:cutoff,state:'completed',phase:'分析完成',error:'',issues:[],rows:[{target,sources:['直接追踪'],state:'done',
  study:{as_of:cutoff,rule_version:'frozen-v1',parameters:{window:20},rows:[{category:'DAY',price:12.123456789}],conflicts:[],policy:'test'},
  evidence:{adjust:'QFQ',requested_count:800,series:[{category:'DAY',snapshot:{metadata:{actual_adjust:'QFQ',category:'DAY'},bars:[{datetime:'2026-10-09 00:00:00',open:12,high:13,low:11,close:12.123456789,vol:100}]}}]}}]})
const record=(url)=>({id:url.split('/').at(-1),kind:'tracking',name:'观察',note:'',revision:1,state:'active',digest:'a'.repeat(64),size_bytes:100,created_at:'2026-10-10T02:01:00Z',updated_at:'2026-10-10T02:01:00Z',deleted_at:null,provenance:'client_archive_not_server_verified'})

test('tracking archive preserves raw input, precision, rules and can import read-only',()=>{
  const p=payload(),draft=trackingArchiveDraft(p);p.rows[0].study.rows[0].price=0
  assert.equal(draft.payload.rows[0].study.rows[0].price,12.123456789)
  const imported=prepareArchiveImport(draft.payload,'snapshot.json')
  assert.equal(imported.draft.kind,'tracking');assert.deepEqual(imported.draft.payload,draft.payload)
})
for(const [name,mutate] of [
  ['missing raw input',p=>delete p.rows[0].evidence],
  ['wrong adjustment',p=>p.rows[0].evidence.adjust='NONE'],
  ['wrong period',p=>p.rows[0].study.rows[0].category='WEEK'],
  ['duplicate target',p=>p.rows.push(p.rows[0])],
  ['false success',p=>p.rows[0].state='cancelled'],
  ['unknown state',p=>p.state='pending'],
])test(name,()=>{const p=payload();mutate(p);assert.throws(()=>validateTrackingArchive(p))})
test('cancelled empty expansion and partially completed batches retain actual states',()=>{
  const p=payload();p.state='cancelled';p.rows=[];p.membership_observed_at='';validateTrackingArchive(p)
  p.state='partial';p.rows=[{target,sources:['直接追踪'],state:'error',error:'data unavailable'}];validateTrackingArchive(p)
})
test('failed upload retries same identity and frozen payload, independent new batch gets a new identity',async()=>{
  const calls=[];let attempt=0
  const store=createTrackingAutoSave(()=> 'alice',async(url,init)=>{calls.push({url,init});return ++attempt===1?Response.json({detail:'空间不足'},{status:413}):Response.json(record(url))})
  const p=payload();await store.save(p);assert.match(store.error.value,/空间不足/);assert.ok(store.pending.value)
  p.rows[0].study.rows[0].price=0
  await store.retry();assert.equal(store.pending.value,null);assert.equal(calls[0].url,calls[1].url);assert.equal(calls[0].init.body,calls[1].init.body)
  assert.equal(calls[1].init.headers.get('X-Research-Owner'),'alice')
  await store.save(payload());assert.notEqual(calls[2].url,calls[1].url)
})
test('late previous-owner save is discarded and never retried as the next account',async()=>{
  let owner='alice',finish,calls=0
  const store=createTrackingAutoSave(()=>owner,(url)=>{calls++;return new Promise(resolve=>{finish=()=>resolve(Response.json(record(url)))})})
  const running=store.save(payload());owner='bob';store.clear();finish();await running
  assert.equal(store.saved.value,null);assert.equal(store.pending.value,null);assert.equal(store.error.value,'')
  await store.retry();assert.equal(calls,1)
})
test('non-finite result stays unsaved rather than converting to null',async()=>{
  let calls=0;const store=createTrackingAutoSave(()=> 'alice',async()=>{calls++;throw Error('must not upload')})
  const p=payload();p.rows[0].study.rows[0].price=NaN
  await store.save(p);assert.equal(calls,0);assert.match(store.error.value,/非有限/)
  await store.retry();assert.equal(calls,0);assert.ok(Number.isNaN(store.pending.value.payload.rows[0].study.rows[0].price))
})
