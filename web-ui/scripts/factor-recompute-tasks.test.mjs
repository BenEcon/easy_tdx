import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {factorRecomputedArchive} from '../src/factor-archive.ts'
import {factorTaskArchive} from '../src/factor-task-review.ts'
import {taskExecution} from '../src/task-execution.ts'
import {submitFactorRecomputeTask,fetchTask,cancelTask} from '../src/api.ts'
const source={id:'00000000-0000-4000-8000-000000000001',digest:'a'.repeat(64),revision:2}
const original=JSON.parse(readFileSync(new URL('../../tests/fixtures/factor_archive/series.json',import.meta.url),'utf8'))
const payload={...original,recomputed_from:{archive_id:source.id,digest:source.digest,revision:2,input_policy:'frozen_inputs_current_implementation',provenance:'client_archive_not_server_verified',original_definitions:original.result.factor_definitions,original_statistics_version:'legacy-unrecorded',configuration_migration:null,horizon_migration:null}}

test('recompute task request binds owner, source revision and manual intent; polling stays automatic',async()=>{
  const before=globalThis.fetch,calls=[]
  globalThis.fetch=async(url,init)=>{calls.push({url,...init});return new Response(JSON.stringify(url.endsWith('/async')?{task_id:'r'}:{task_id:'r',status:'done',kind:'factor_recompute',result:payload}))}
  try{
    const job=taskExecution({owner:()=> 'alice',submit:submitFactorRecomputeTask,poll:fetchTask,cancel:cancelTask,interval:0,timeout:1000})
    const req={source_archive_id:source.id,expected_digest:source.digest,expected_revision:2}
    assert.equal(await job.run(req,true),true)
    assert.match(calls[0].url,/recompute\/async$/)
    assert.deepEqual(JSON.parse(calls[0].body),req)
    assert.equal(new Headers(calls[0].headers).get('X-Research-Owner'),'alice')
    assert.equal(new Headers(calls[0].headers).get('X-Task-Owner'),'alice')
    assert.deepEqual(calls.map(c=>new Headers(c.headers).get('X-Query-Origin')),['user',null])
  }finally{globalThis.fetch=before}
})

test('history retains the complete recompute envelope, not just numerical results',()=>{
  const frozen=structuredClone(payload)
  const state={task_id:'r',status:'done',kind:'factor_recompute',result:frozen}
  const actual=factorTaskArchive(state,'r')
  assert.deepEqual(actual,payload);assert.notEqual(actual,frozen)
  frozen.recomputed_from.digest='b'.repeat(64)
  assert.equal(actual.recomputed_from.digest,source.digest)
  assert.deepEqual(factorRecomputedArchive(payload,source),payload)
  for(const patch of [{id:'different'},{digest:'b'.repeat(64)},{revision:3}])assert.throws(()=>factorRecomputedArchive(payload,{...source,...patch}),/来源不一致/)
  for(const patch of [{revision:true},{digest:''},{original_definitions:null},{input_policy:'live'}, {archive_id:'bad'}])assert.throws(()=>factorRecomputedArchive({...payload,recomputed_from:{...payload.recomputed_from,...patch}}))
  assert.throws(()=>factorTaskArchive({...state,status:'cancelled'},'r'))
})

test('replay uses shared task invalidation and archive saving preserves replay metadata',()=>{
  const file=n=>readFileSync(new URL(`../src/${n}`,import.meta.url),'utf8')
  const view=file('components/FactorArchiveRecompute.vue')
  assert.match(view,/submit:submitFactorRecomputeTask,poll:fetchTask,cancel:cancelTask/)
  assert.match(view,/task.clear\(\)/);assert.match(view,/onBeforeUnmount\(reset\)/)
  assert.match(view,/factorRecomputedArchive\(task.result.value,source\)/)
  assert.match(view,/取消后台任务/);assert.match(view,/停止等待/)
  assert.match(view,/payload:result.value/)
  assert.doesNotMatch(view,/fetch\('\/api\/v1\/research\/factors\/recompute'/)
  assert.match(file('components/FactorTaskReview.vue'),/:payload="payload"/)
  assert.match(file('components/FactorArchiveTools.vue'),/if\(props.payload\)/)
  assert.match(file('views/CompareView.vue'),/t.kind !== 'factor_recompute'/)
})
