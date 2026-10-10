import test from 'node:test'
import assert from 'node:assert/strict'
import { archiveClient, freezeArchiveDraft, validateArchiveDirectory, validateArchiveRecord } from '../src/cloud-archives.ts'

const record={id:'00000000-0000-4000-8000-000000000001',kind:'chart',name:'研究',note:'',revision:1,state:'active',digest:'a'.repeat(64),size_bytes:15,created_at:'2026-10-09T12:00:00+00:00',updated_at:'2026-10-09T12:00:00+00:00',deleted_at:null,provenance:'client_archive_not_server_verified'}
const directory={revision:0,items:[],quota:{used_bytes:0,max_bytes:128e6,used_items:0,max_items:100,object_bytes:25e6,used_receipts:0,max_receipts:1000}}

test('archive requests bind current owner and bypass browser cache',async()=>{
  let observed
  const api=archiveClient(()=> 'alice',async (url,init)=>{observed={url,init}; return Response.json(directory)})
  assert.deepEqual(await api(),directory)
  assert.equal(observed.init.headers.get('X-Research-Owner'),'alice')
  assert.equal(observed.init.cache,'no-store')
  assert.equal(observed.init.credentials,'same-origin')
})

test('cloud directory validates all rows, quotas and identities without dropping broken entries',async()=>{
  const good={...directory,items:[record],quota:{...directory.quota,used_items:1,used_bytes:15}}
  assert.equal(validateArchiveDirectory(good),good)
  for (const bad of [null,{}, {...good,items:null},{...good,quota:null},{...good,revision:-1},
    {...good,quota:{...good.quota,used_items:2}}, {...good,items:[record,record],quota:{...good.quota,used_items:2}},
    ...[{updated_at:null},{created_at:'2026-02-30T12:00:00Z'},{updated_at:'2026-10-09'},
      {id:'../x'},{revision:0},{digest:'x'},{kind:'unknown'},{kind:['chart']},{state:['active']},
      {state:'purged'},{note:[]},{deleted_at:42}].map(patch=>({...good,items:[{...record,...patch}]}))]) {
    await assert.rejects(archiveClient(()=>'alice',async()=>Response.json(bad))(),/响应格式不正确/)
  }
})
test('original detail requires an object payload but action receipts may omit it',async()=>{
  assert.equal(validateArchiveRecord(record),record)
  assert.throws(()=>validateArchiveRecord(record,true),/响应格式/)
  assert.throws(()=>validateArchiveRecord({...record,payload:[]},true),/响应格式/)
  const original={...record,payload:{unknown_future_field:{precise:0.123456789}}}
  assert.equal(validateArchiveRecord(original,true),original)
  await assert.rejects(archiveClient(()=>'alice',async()=>Response.json(record))('/'+record.id),/响应格式/)
  assert.deepEqual(await archiveClient(()=>'alice',async()=>Response.json(record))('/'+record.id+'/actions',{method:'POST'}),record)
})
test('account change discards delayed success and delayed errors',async()=>{
  for(const status of [200,409]) {
    let user='alice', release
    const api=archiveClient(()=>user,()=>new Promise(resolve=>release=resolve))
    const pending=api();user='bob';release(Response.json({secret:'old'}, {status}))
    await assert.rejects(pending,/旧账户响应/)
  }
})
test('unauthenticated archive requests do not reach server; structured conflicts remain actionable',async()=>{
  let called=false
  await assert.rejects(archiveClient(()=>undefined,async()=>{called=true})(),/登录/)
  assert.equal(called,false)
  await assert.rejects(archiveClient(()=>'alice',async()=>Response.json({detail:'其他设备已修改'},{status:409}))(),error=>error.status===409&&error.message==='其他设备已修改')
})
test('upload retries retain immutable captured body and all numerical precision',()=>{
  const original={kind:'chart',name:'研究',note:'',payload:{bars:[{close:1.123456789}],periods:['DAY','MIN_30']}}
  const captured=freezeArchiveDraft(original);original.payload.bars[0].close=9
  assert.equal(captured.payload.bars[0].close,1.123456789)
  assert.deepEqual(captured.payload.periods,['DAY','MIN_30'])
  assert.throws(()=>freezeArchiveDraft({...original,name:' '}))
  assert.throws(()=>freezeArchiveDraft({...original,note:'x'.repeat(4001)}))
  assert.throws(()=>freezeArchiveDraft({...original,payload:{value:NaN}}),/非有限/)
})
