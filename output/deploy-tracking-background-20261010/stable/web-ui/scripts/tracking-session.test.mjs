import test from 'node:test'
import assert from 'node:assert/strict'
import {effectScope,watch} from 'vue'
import {createTrackingSession} from '../src/tracking-session.ts'
import {analyzeTrackingTarget} from '../src/tracking-analysis.ts'
import {fetchBoardMembers,fetchResearchSnapshot} from '../src/api.ts'
import {readFileSync} from 'node:fs'

const stock={kind:'stock',market:'SZ',code:'300750',name:'宁德时代'}
const group=()=>({id:'g',name:'示例组',targets:[stock,{...stock,code:'300450',name:'先导智能'}]})
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
const study=()=>({as_of:'2026-10-10 10:00:00',rows:[{category:'DAY',price:1}],policy:'',rule_version:'test',parameters:{},conflicts:[]})
const adapter=(analyze)=>({now:()=> '2026-10-10 10:00:00',members:async()=>{throw Error('no boards')},analyze})

test('route consumer can unmount and remount while the one sequential analysis continues',async()=>{
  const job=createTrackingSession();job.setOwner('alice');job.selectedId.value='g'
  const gate=deferred(),started=deferred();let calls=0,signalSeen,seen=[]
  const view=effectScope();view.run(()=>watch(job.rows,r=>seen.push(r.map(x=>x.state)),{flush:'sync'}))
  const source=group()
  const run=job.run(source,'revision-1',adapter(async(t,periods,cutoff,signal,owner)=>{
    calls++;signalSeen=signal;assert.equal(owner,'alice');assert.deepEqual(periods,['DAY'])
    if(calls===1){started.resolve();await gate.promise}return study()
  }))
  await started.promise;assert.equal(job.loading.value,true);assert.equal(calls,1)
  view.stop();source.targets[0]={...stock,name:'changed'};source.name='changed'
  await job.run(group(),'other',adapter(()=>{throw Error('duplicate must not start')}))
  assert.equal(signalSeen.aborted,false)
  gate.resolve();await run
  assert.equal(calls,2);assert.equal(job.phase.value,'分析完成');assert.equal(job.completed.value,2)
  const returned=effectScope();let restored
  returned.run(()=>watch(job.rows,r=>restored=r,{immediate:true}))
  assert.equal(restored.length,2);assert.equal(job.snapshot.value.group.name,'示例组')
  assert.equal(job.snapshot.value.group.targets[0].name,'宁德时代');returned.stop()
})

test('explicit stop retains completed rows and marks running/unstarted rows cancelled',async()=>{
  const job=createTrackingSession();job.setOwner('alice')
  const gate=deferred(),second=deferred();let count=0
  const source=group();source.targets.push({...stock,code:'300443'})
  const run=job.run(source,'r',adapter(async()=>{count++;if(count===2){second.resolve();await gate.promise}return study()}))
  await second.promise;job.stop();gate.resolve();await run
  assert.deepEqual(job.rows.value.map(r=>r.state),['done','cancelled','cancelled'])
  assert.equal(job.loading.value,false);assert.equal(job.successful.value,1)
  assert.match(job.phase.value,/已停止/);assert.equal(count,2)
})

test('owner change or revoked access clears results and rejects late old publications',async()=>{
  const job=createTrackingSession();job.setOwner('alice');const gate=deferred(),started=deferred()
  const old=job.run(group(),'r',adapter(async()=>{started.resolve();await gate.promise;return study()}))
  await started.promise;job.setOwner('bob');assert.deepEqual(job.rows.value,[]);assert.equal(job.snapshot.value,null)
  await job.run(group(),'b',adapter(async()=>study()))
  gate.resolve();await old;assert.equal(job.owner.value,'bob');assert.equal(job.snapshot.value.revision,'b');assert.equal(job.completed.value,2)
  job.setOwner('');await job.run(group(),'x',adapter(()=>{throw Error('unauthorized')}))
  assert.equal(job.snapshot.value,null);assert.deepEqual(job.rows.value,[])
})

test('background completion includes per-target failure and expansion failure without false success',async()=>{
  const job=createTrackingSession();job.setOwner('alice')
  const source=group();source.targets.push({kind:'board',market:'1',code:'881001',name:'行业',boardType:'HY'})
  await job.run(source,'r',adapter(async t=>{if(t.kind==='board')throw Error('node failed');return study()}))
  assert.equal(job.issues.value.length,1);assert.equal(job.failed.value,1)
  assert.match(job.phase.value,/未完成/);assert.equal(job.rows.value.length,3)
})

test('cancel during board expansion cannot publish late entries',async()=>{
  const job=createTrackingSession();job.setOwner('alice');const gate=deferred(),started=deferred()
  const source={id:'b',name:'板块',targets:[{kind:'board',market:'1',code:'881001',name:'行业',boardType:'HY'}]}
  let analyzed=0
  const run=job.run(source,'r',{...adapter(async()=>{analyzed++;return study()}),members:async()=>{started.resolve();await gate.promise;return {data:[{code:'300750',market:0}],count:1}}})
  await started.promise;job.stop();gate.resolve();await run
  assert.equal(analyzed,0);assert.deepEqual(job.rows.value,[]);assert.equal(job.loading.value,false)
})

test('tracking transport binds owner, stops on permission failure and does not relabel name/market requests',async()=>{
  const original=globalThis.fetch,calls=[];const abort=new AbortController();let denied=0
  globalThis.fetch=async(url,init)=>{calls.push({url,init});return Response.json({detail:'权限撤销'},{status:403})}
  try {
    await assert.rejects(analyzeTrackingTarget(stock,['DAY','WEEK'],'2026-10-10 10:00:00',abort.signal,'alice',()=>{denied++;abort.abort()}))
    assert.equal(denied,1);assert.equal(calls.length,1)
    assert.equal(calls[0].init.headers['X-Tracking-Owner'],'alice')
    // This release keeps the production query-origin behavior unchanged.
    assert.equal(calls[0].init.headers['X-Query-Origin'],undefined)
    await assert.rejects(fetchBoardMembers('881001',100000,undefined,'alice'))
    assert.equal(calls[1].init.headers['X-Tracking-Owner'],'alice')
    await assert.rejects(fetchResearchSnapshot({kind:'index',market:'SH',code:'000001'},'DAY',800,'NONE',undefined,'alice'))
    assert.equal(calls[2].init.headers['X-Tracking-Owner'],'alice')
  } finally {globalThis.fetch=original}
})

test('late auth error on an already-cancelled old transport never stops the next job',async()=>{
  const original=globalThis.fetch,gate=deferred(),abort=new AbortController();let denied=0
  globalThis.fetch=()=>gate.promise
  try {
    const old=analyzeTrackingTarget(stock,['DAY'],'2026-10-10 10:00:00',abort.signal,'old',()=>denied++)
    abort.abort();gate.resolve(Response.json({detail:'账户已切换'},{status:409}))
    await assert.rejects(old);assert.equal(denied,0)
  } finally {globalThis.fetch=original}
})

test('route delegates lifetime and owns bounded vertical scrolling; application binds ownership',()=>{
  const view=readFileSync(new URL('../src/views/TrackingView.vue',import.meta.url),'utf8')
  assert.doesNotMatch(view,/onBeforeUnmount/);assert.match(view,/trackingSession\.run/)
  assert.match(view,/height:100%;min-height:0;overflow-y:auto/)
  assert.match(view,/max-height:min\(760px,65dvh\)/)
  const shared=readFileSync(new URL('../src/tracking-background.ts',import.meta.url),'utf8')
  assert.match(shared,/canUseTracking/);assert.match(shared,/flush:'sync'/)
})
