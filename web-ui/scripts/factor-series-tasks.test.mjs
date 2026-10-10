import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {taskExecution} from '../src/task-execution.ts'
import {submitFactorSeriesTask,fetchTask,cancelTask} from '../src/api.ts'
import {factorTaskArchive} from '../src/factor-task-review.ts'
import {initializeFactorCatalog} from '../src/factor-catalog.ts'
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/factor_archive/series.json',import.meta.url),'utf8'))

test('series automatic initialization is system intent, only deliberate task submission is a query',async()=>{
  const original=globalThis.fetch,calls=[]
  globalThis.fetch=async(url,options)=>{
    calls.push({url,...options})
    return new Response(JSON.stringify(url.endsWith('/async')?{task_id:'series-job'}:{task_id:'series-job',kind:'factor_series',status:'done',result:fixture.result}))
  }
  try{
    for(const manual of [false,true]){
      const job=taskExecution({owner:()=> 'alice',submit:submitFactorSeriesTask,poll:fetchTask,cancel:cancelTask,interval:0,timeout:1000})
      assert.equal(await job.run(fixture.result.settings,manual),true)
      assert.deepEqual(job.result.value,fixture.result)
    }
    assert.match(calls[0].url,/factors\/compute\/async$/)
    assert.deepEqual(calls.map(c=>new Headers(c.headers).get('X-Query-Origin')),['system',null,'user',null])
    assert.ok(calls.every(c=>new Headers(c.headers).get('X-Task-Owner')==='alice'))
  }finally{globalThis.fetch=original}
})

test('saved series task reopens as series without lookup, all diagnostics and original inputs survive',()=>{
  const payload=factorTaskArchive({task_id:'s',kind:'factor_series',status:'done',result:fixture.result},'s')
  assert.equal(payload.mode,'series');assert.deepEqual(payload.result,fixture.result)
  assert.notEqual(payload.result,fixture.result)
  assert.equal(payload.result.rows.length,160);assert.ok(payload.result.errors.pe_ratio)
  for(const status of ['pending','running','cancelling','cancelled','failed'])assert.throws(()=>factorTaskArchive({task_id:'s',kind:'factor_series',status,result:fixture.result},'s'))
})

test('cleared series execution cannot publish an old stock result',async()=>{
  let resolve,polled
  const pending=new Promise(r=>resolve=r),ready=new Promise(r=>polled=r)
  const job=taskExecution({owner:()=> 'alice',submit:async()=>({task_id:'old'}),poll:()=>{polled();return pending},interval:0,timeout:1000})
  const run=job.run(fixture.result.settings);await ready;job.clear()
  resolve({task_id:'old',status:'done',result:fixture.result})
  assert.equal(await run,false);assert.equal(job.result.value,null);assert.equal(job.state.value,null)
})

test('live series and history use shared tasks, invalidate on input/account/route and never treat as trading backtest',()=>{
  const file=n=>readFileSync(new URL(`../src/${n}`,import.meta.url),'utf8')
  const view=file('views/QuantResearchView.vue')
  assert.match(view,/submit:submitFactorSeriesTask,poll:fetchTask,cancel:cancelTask/)
  assert.match(view,/factorTask.run\(/);assert.match(view,/\},manual\)/)
  assert.match(view,/factorGeneration\+\+; factorTask.clear\(\)/)
  assert.match(view,/watch\(tab,clearFactorResult,\{flush:'sync'\}\)/)
  assert.match(view,/onBeforeUnmount\(\(\) => \{ pageActive=false; clearFactorResult\(\) \}\)/)
  assert.match(view,/factorArchiveDraft\('series',result\)/)
  assert.match(view,/停止等待/);assert.match(view,/取消后台任务/)
  assert.doesNotMatch(view,/computeResearchFactors\(/)
  assert.match(file('components/BackgroundTasks.vue'),/factor_series/)
  assert.match(file('views/CompareView.vue'),/t.kind !== 'factor_series'/)
})

test('late catalog never submits after unmount, input/account/tab changes, or manual run',async()=>{
  for(const change of ['none','unmount','input','account','tab','manual']){
    let resolve,active=true,current=true
    const published=[],runs=[],failures=[]
    const load=new Promise(r=>resolve=r)
    const job=initializeFactorCatalog({load:()=>load,active:()=>active,initialContext:()=>current,publish:v=>published.push(v),fail:e=>failures.push(e),run:async()=>{runs.push('run')}})
    if(change==='unmount')active=false
    else if(change!=='none')current=false
    resolve([{name:'momentum_20d'}]);await job
    assert.equal(published.length,change==='unmount'?0:1)
    assert.equal(runs.length,change==='none'?1:0)
    assert.deepEqual(failures,[])
  }
})

test('failed catalog does not silently start default research or publish after leaving',async()=>{
  for(const active of [true,false]){
    const failures=[]
    await initializeFactorCatalog({load:async()=>{throw Error('catalog failed')},active:()=>active,initialContext:()=>true,publish:()=>assert.fail('must not publish'),fail:e=>failures.push(e.message),run:async()=>assert.fail('must not run')})
    assert.deepEqual(failures,active?['catalog failed']:[])
  }
})
