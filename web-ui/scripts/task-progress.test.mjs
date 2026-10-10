import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {validateTaskProgress,taskProgressLabel} from '../src/task-progress.ts'
import {factorTaskArchive} from '../src/factor-task-review.ts'
import {taskExecution} from '../src/task-execution.ts'
const point={phase:'factor_values',completed:2,total:8,detail:'momentum_20d',sequence:3}
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/factor_archive/multi-horizon.json',import.meta.url),'utf8'))

test('progress is bounded, readable work units rather than inferred total percent',()=>{
  assert.deepEqual(validateTaskProgress(point),point)
  assert.equal(validateTaskProgress(null),null)
  assert.match(taskProgressLabel(point),/因子值 · 标的 2\/8 · momentum_20d/)
  assert.doesNotMatch(taskProgressLabel({...point,completed:8}),/100%|已完成/)
  for(const change of [{completed:true},{completed:9},{completed:-1},{total:0},{sequence:0},{sequence:NaN},{phase:'unknown'},{phase:['factor_values']},{detail:'x'.repeat(97)},{detail:'𠮷'.repeat(97)},{extra:0}])assert.throws(()=>validateTaskProgress({...point,...change}))
  assert.equal(validateTaskProgress({...point,detail:'𠮷'.repeat(96)}).detail,'𠮷'.repeat(96))
  assert.match(taskProgressLabel({phase:'bad'}),/以任务状态为准/)
})

test('factor result review freezes complete task data without lookup or recomputation',()=>{
  const state={task_id:'a',kind:'factor_evaluation',status:'done',result:structuredClone(fixture.result)}
  const payload=factorTaskArchive(state,'a')
  assert.deepEqual(payload.result,fixture.result)
  assert.equal(payload.result.input_snapshots.length,5)
  assert.deepEqual(payload.result.settings.horizons,[1,5,10,20])
  state.result.settings.horizons=[20]
  assert.deepEqual(payload.result.settings.horizons,[1,5,10,20])
  assert.notEqual(payload.result,state.result)
  for(const patch of [{task_id:'b'},{kind:'backtest'},{status:'running'},{status:'cancelled'},{result:null}])assert.throws(()=>factorTaskArchive({...state,...patch},'a'))
})

test('completed phase never publishes result while task is still running',async()=>{
  let calls=0,release
  const pending=new Promise(r=>release=r)
  const job=taskExecution({owner:()=> 'alice',submit:async()=>({task_id:'a'}),poll:async()=>++calls===1?{task_id:'a',status:'running',result:null,progress:{...point,completed:8}}:pending,interval:0,timeout:1000})
  const run=job.run({});await new Promise(r=>setTimeout(r,15))
  assert.equal(job.running.value,true);assert.equal(job.result.value,null)
  assert.equal(job.state.value.progress.completed,8)
  release({task_id:'a',status:'failed',result:null,error:'full result exceeds budget'})
  assert.equal(await run,false);assert.equal(job.result.value,null)
})

test('untrusted progress cannot be used to publish an apparently completed task',async()=>{
  const job=taskExecution({owner:()=> 'alice',submit:async()=>({task_id:'a'}),poll:async()=>({task_id:'a',status:'done',result:{ok:true},progress:{...point,total:0}}),interval:0,timeout:1000})
  assert.equal(await job.run({}),false);assert.equal(job.result.value,null);assert.match(job.error.value,/进度/)
})

test('historical review uses owner-bound read-only fetch and account invalidation',()=>{
  const review=readFileSync(new URL('../src/components/FactorTaskReview.vue',import.meta.url),'utf8')
  assert.match(review,/fetchTask\(props.taskId,\{owner,signal:controller.signal\}\)/)
  assert.match(review,/currentUser.value\?\.id===owner/)
  assert.match(review,/flush:'sync'/)
  assert.match(review,/controller\?\.abort\(\)/)
  assert.match(review,/onBeforeUnmount\(close\)/)
  assert.match(review,/@cancel.prevent="close"/)
  assert.match(review,/returnFocus=trigger.value\?\?null/)
  assert.match(review,/nextTick\(\(\)=>\{if\(generation===stamp&&target\?\.isConnected\)/)
  assert.doesNotMatch(review,/submitFactor|evaluateResearch|computeResearch/)
  const account=readFileSync(new URL('../src/views/AccountView.vue',import.meta.url),'utf8')
  assert.match(account,/<BackgroundTasks :key="currentUser\?\.id"/)
  const compare=readFileSync(new URL('../src/views/CompareView.vue',import.meta.url),'utf8')
  assert.match(compare,/t.kind !== 'factor_evaluation'/)
})
