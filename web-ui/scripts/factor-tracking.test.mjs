import test from 'node:test'
import assert from 'node:assert/strict'
import {factorTrackingClient,trackingEquity,trackingScoreOptions,trackingScoreRows} from '../src/factor-tracking.ts'
import {readTrackingBook} from '../src/tracking.ts'
const source={format:'factor-tracking-source-v1',archive_id:'11111111-1111-1111-1111-111111111111',archive_digest:'a'.repeat(64),archive_revision:1,title:'冻结研究',score_key:'x',score_label:'测试因子',date:'2026-10-09',input_fingerprint:'b'.repeat(64),selection:[{symbol:'SZ:000001',score:.000123456789}],provenance:'client_archive_not_server_verified',names:'user_display_labels_not_historical_security_master'}
const group={id:'test-group',name:'观察',targets:[{kind:'stock',market:'SZ',code:'000001',name:'平安银行'}],research_source:source}
const record={id:source.archive_id,kind:'factor',state:'active',digest:source.archive_digest,revision:1}
const choice={name:'观察',score_key:'x',symbols:['SZ:000001'],labels:{'SZ:000001':'平安银行'}}

test('explicit stock-only finite latest selection; missing and fund/index stay unavailable',()=>{
  for(const s of ['SZ:000001','SZ:300750','SH:600036','BJ:920001'])assert.equal(trackingEquity(s),true)
  for(const s of ['SH:000001','SZ:399001','SH:510300','SZ:159915','SZ:600036'])assert.equal(trackingEquity(s),false)
  const result={settings:{factors:['x','bad']},errors:{bad:'missing'},latest:[{code:'SZ:000001',x:.1},{code:'SH:600036',x:null},{code:'SH:510300',x:.3}],composition:{error:null,latest:[{code:'SZ:000001',score:0}]}}
  assert.deepEqual(trackingScoreOptions(result).map(r=>r.value),['composite_score','x'])
  assert.deepEqual(trackingScoreRows(result,'x').filter(r=>r.eligible).map(r=>r.code),['SZ:000001'])
  assert.equal(trackingScoreRows(result,'composite_score')[0].value,0)
  assert.deepEqual(trackingScoreRows(result,'bad'),[])
})
test('origin and precision survive JSON and later group membership edits',()=>{
  const book=readTrackingBook({version:1,revision:'r',groups:[structuredClone(group)]})
  book.groups[0].targets=[];book.groups[0].name='后来修改'
  assert.deepEqual(readTrackingBook(JSON.parse(JSON.stringify(book))).groups[0].research_source,source)
  const bad=structuredClone(book);bad.groups[0].research_source.selection[0].score=NaN
  assert.throws(()=>readTrackingBook(bad),/来源/)
})
test('only explicit action writes owner assertion and source revision, never sends computed score',async()=>{
  let calls=0
  const client=factorTrackingClient(()=> 'alice',async(url,init)=>{
    calls++;assert.match(url,/tracking-group$/);assert.equal(init.headers['X-Research-Owner'],'alice')
    const body=JSON.parse(init.body);assert.equal(body.digest,source.archive_digest);assert.equal(body.revision,1);assert.equal(body.score,undefined)
    return Response.json({group,created:true})
  })
  assert.equal(calls,0)
  const result=await client.create(record,choice,new AbortController().signal)
  assert.equal(result.group.research_source.selection[0].score,.000123456789);assert.equal(calls,1)
})
test('late owner response rejected; permission denial and source mismatch not successful',async()=>{
  let owner='alice',finish
  const client=factorTrackingClient(()=>owner,()=>new Promise(resolve=>{finish=()=>resolve(Response.json({group,created:true}))}))
  const pending=client.create(record,choice,new AbortController().signal);owner='bob';finish()
  await assert.rejects(pending,/账户已切换/)
  const denied=factorTrackingClient(()=>owner,async()=>Response.json({detail:'没有权限'},{status:403}))
  await assert.rejects(denied.create(record,choice,new AbortController().signal),/没有权限/)
  const mismatch=factorTrackingClient(()=>owner,async()=>Response.json({group:{...group,research_source:{...source,archive_digest:'c'.repeat(64)}},created:true}))
  await assert.rejects(mismatch.create(record,choice,new AbortController().signal),/来源不一致/)
})
