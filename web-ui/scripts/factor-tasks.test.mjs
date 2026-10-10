import test from 'node:test'
import assert from 'node:assert/strict'
import {taskExecution} from '../src/task-execution.ts'
import {submitFactorEvaluationTask,fetchTask,cancelTask} from '../src/api.ts'
import {readFileSync} from 'node:fs'

const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve}}
const tick=()=>new Promise(setImmediate)
const state=(status)=>({task_id:'factor-job',status,elapsed:2,result:null,error:null})
function setup(cancel){
  const identity={owner:'alice'},polls=[]
  const job=taskExecution({owner:()=>identity.owner,submit:async()=>({task_id:'factor-job'}),poll:()=>{const p=deferred();polls.push(p);return p.promise},cancel,interval:0,timeout:1000})
  return{job,identity,polls}
}

test('factor submission marks only explicit dispatch, preserves owner/signal, polling/cancel stay automatic',async()=>{
  const old=globalThis.fetch,seen=[],context={owner:'alice',signal:new AbortController().signal}
  globalThis.fetch=async(url,options)=>{
    seen.push({url,...options})
    return new Response(JSON.stringify(url.endsWith('/async')?{task_id:'factor-job'}:{...state('done'),result:{version:'fixture'}}))
  }
  try{
    const job=taskExecution({owner:()=>context.owner,submit:submitFactorEvaluationTask,poll:fetchTask,cancel:cancelTask,interval:0,timeout:1000})
    assert.equal(await job.run({stocks:[],factors:['momentum_20d']}),true)
    await cancelTask('factor-job',context)
    assert.match(seen[0].url,/factors\/evaluate\/async$/)
    assert.deepEqual(seen.map(r=>new Headers(r.headers).get('X-Query-Origin')),['user',null,'system'])
    assert.ok(seen.every(r=>new Headers(r.headers).get('X-Task-Owner')==='alice'))
    assert.equal(seen[2].signal,context.signal)
  }finally{globalThis.fetch=old}
})

test('cancel acknowledged during pending poll cannot regress UI or publish partial result',async()=>{
  let cancelContext
  const h=setup(async(id,c)=>{cancelContext=c;return state('cancelling')})
  const run=h.job.run({factors:['momentum_20d']});await tick()
  await h.job.cancel()
  assert.equal(cancelContext.owner,'alice');assert.equal(h.job.state.value.status,'cancelling')
  h.polls[0].resolve(state('running'));await new Promise(r=>setTimeout(r,10))
  assert.equal(h.job.state.value.status,'cancelling');assert.equal(h.job.running.value,true)
  h.polls[1].resolve(state('cancelled'))
  assert.equal(await run,false);assert.equal(h.job.result.value,null);assert.equal(h.job.state.value.status,'cancelled')
})

test('late cancellation cannot revive cleared or changed-account task UI',async()=>{
  const late=deferred(),h=setup(()=>late.promise)
  const run=h.job.run({});await tick();const cancel=h.job.cancel()
  h.identity.owner='bob';h.job.clear();late.resolve(state('cancelling'));await cancel
  h.polls[0].resolve(state('cancelled'));await run
  assert.equal(h.job.state.value,null);assert.equal(h.job.cancelError.value,'');assert.equal(h.job.cancelling.value,false)
})

test('unconfirmed cancellation keeps polling; successful task remains recoverable',async()=>{
  const h=setup(async()=>{throw Error('network lost')})
  const run=h.job.run({});await tick();await h.job.cancel()
  assert.match(h.job.cancelError.value,/network lost/);assert.equal(h.job.running.value,true)
  h.polls[0].resolve({...state('done'),result:{complete:true}})
  assert.equal(await run,true);assert.deepEqual(h.job.result.value,{complete:true})
})

test('factor panel uses shared execution and distinguishes cancel from detach',()=>{
  const source=readFileSync(new URL('../src/components/FactorEvaluationPanel.vue',import.meta.url),'utf8')
  assert.match(source,/submit:submitFactorEvaluationTask,poll:fetchTask,cancel:cancelTask/)
  assert.match(source,/watch\(inputKey,invalidate,\{flush:'sync'\}\)/)
  assert.match(source,/onBeforeUnmount\(invalidate\)/)
  assert.match(source,/取消后台任务/);assert.match(source,/停止等待/)
  assert.doesNotMatch(source,/await.*evaluateResearchFactors\(/)
})
