import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'
import { taskExecution } from '../src/task-execution.ts'
import { queryIntentHeaders } from '../src/query-origin.ts'
import {submitPortfolioTask,submitMultiStrategyTask,submitOptimizeTask,submitOptimizeAllTask,submitSignalScanTask,fetchTask} from '../src/api.ts'

const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
const tick=()=>new Promise(setImmediate)
const done=(id,result={value:123})=>({task_id:id,status:'done',result,error:null})
function setup(overrides={}){
  const identity={owner:'alice'},calls=[]
  const slot=taskExecution({owner:()=>identity.owner,timeout:1000,interval:0,
    submit:async(input,context)=>{calls.push({input,context,origin:queryIntentHeaders()['X-Query-Origin']});return{task_id:'a'}},
    poll:async(id,context)=>{calls.push({id,context,origin:queryIntentHeaders()['X-Query-Origin']});return done(id)},...overrides})
  return{slot,identity,calls}
}
test('task stores detached actual inputs, user submission and system polling',async()=>{
  const pending=deferred(),h=setup({submit:async(input,context)=>{h.calls.push({input,context,origin:queryIntentHeaders()['X-Query-Origin']});return pending.promise}})
  const input=reactive({stocks:['SZ:300450'],params:{fast:7},cash:200000,adjust:'HFQ'})
  const run=h.slot.run(input)
  input.stocks.push('SH:600000');input.params.fast=99;input.adjust='NONE'
  h.calls[0].input.params.fast=77
  pending.resolve({task_id:'a'});assert.equal(await run,true)
  assert.deepEqual(h.slot.request.value,{stocks:['SZ:300450'],params:{fast:7},cash:200000,adjust:'HFQ'})
  assert.equal(h.calls[0].context.owner,'alice');assert.deepEqual(h.calls.map(c=>c.origin),['user','system'])
})
for(const stage of ['submit','poll'])for(const outcome of ['resolve','reject'])test(`invalidated ${stage} ${outcome} cannot revive result/error/spinner`,async()=>{
  const pending=deferred(),h=setup({[stage]:()=>pending.promise})
  const run=h.slot.run({cash:1});await tick();h.slot.clear()
  if(outcome==='resolve')pending.resolve(stage==='submit'?{task_id:'a'}:done('a'));else pending.reject(Error('late'))
  assert.equal(await run,false);assert.equal(h.slot.result.value,null);assert.equal(h.slot.request.value,null)
  assert.equal(h.slot.error.value,'');assert.equal(h.slot.running.value,false)
})
test('earlier request completion cannot stop a newer task or replace its context',async()=>{
  const a=deferred(),b=deferred();let n=0
  const h=setup({poll:()=>++n===1?a.promise:b.promise})
  const first=h.slot.run({cash:1});await tick()
  const second=h.slot.run({cash:2});await tick()
  a.resolve(done('a'));assert.equal(await first,false);assert.equal(h.slot.running.value,true)
  b.resolve(done('a',{latest:true}));assert.equal(await second,true);assert.equal(h.slot.request.value.cash,2)
})
test('owner change stops polling and cannot attribute prior account result to the new account',async()=>{
  const pending=deferred(),h=setup({poll:()=>pending.promise})
  const run=h.slot.run({cash:1});await tick();h.identity.owner='bob';h.slot.clear()
  pending.resolve(done('a'));assert.equal(await run,false);assert.equal(h.slot.result.value,null)
  h.identity.owner=undefined;assert.equal(await h.slot.run({cash:2}),false);assert.match(h.slot.error.value,/登录/)
})
for(const status of ['failed','cancelled','timed_out'])test(`${status} remains failure, never successful completion`,async()=>{
  const h=setup({poll:async()=>({task_id:'a',status,result:null,error:'failure detail'})})
  assert.equal(await h.slot.run({}),false);assert.ok(h.slot.error.value);assert.equal(h.slot.result.value,null)
})
test('cancelling is not completed; wrong ID, malformed result and unknown status fail closed',async()=>{
  let count=0
  const h=setup({poll:async()=>++count===1?{task_id:'a',status:'cancelling',result:null}:done('a')})
  assert.equal(await h.slot.run({}),true);assert.equal(count,2)
  for(const bad of [done('b'),done('a',null),{task_id:'a',status:'unknown',result:null}]){
    const x=setup({poll:async()=>bad});assert.equal(await x.slot.run({}),false);assert.equal(x.slot.result.value,null);assert.ok(x.slot.error.value)
  }
})
test('deadline aborts polling and explicitly says the server may still be running',async()=>{
  const h=setup({timeout:15,poll:(_id,context)=>new Promise((_,reject)=>context.signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true}))})
  assert.equal(await h.slot.run({}),false);assert.match(h.slot.error.value,/任务可能仍在计算/);assert.equal(h.slot.result.value,null)
})
test('task API sends captured owner and abort signal; old callers remain compatible',async()=>{
  const original=globalThis.fetch,seen=[],context={owner:'alice',signal:new AbortController().signal}
  globalThis.fetch=async(url,init)=>{seen.push({url:String(url),...init});return new Response(JSON.stringify(done('a')),{status:200})}
  try{
    for(const submit of [submitPortfolioTask,submitMultiStrategyTask,submitOptimizeTask,submitOptimizeAllTask,submitSignalScanTask])await submit({},context)
    await fetchTask('a/b',context);await fetchTask('legacy')
    for(const req of seen.slice(0,6)){assert.equal(new Headers(req.headers).get('X-Task-Owner'),'alice');assert.equal(req.signal,context.signal)}
    assert.match(seen[5].url,/a%2Fb$/);assert.equal(new Headers(seen[6].headers).get('X-Task-Owner'),null)
  }finally{globalThis.fetch=original}
})
