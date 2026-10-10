import test from 'node:test'
import assert from 'node:assert/strict'
import { analyzeTrackingEntries, emptyTrackingBook, expandTrackingGroup, readTrackingBook, researchTarget, trackingAdjustment, trackingBreadth, trackingChartQuery, trackingKey, validateTrackingTarget } from '../src/tracking.ts'
const stock={kind:'stock',market:'SZ',code:'000001',name:'平安银行'}
const index={kind:'index',market:'SH',code:'000001',name:'上证指数'}
const board={kind:'board',market:'1',code:'881001',name:'行业甲',boardType:'HY'}
const fund={kind:'fund',market:'SH',code:'510300',name:'沪深300ETF'}
test('tracking identity separates asset types, exchanges and board catalogues',()=>{
  assert.notEqual(trackingKey(stock),trackingKey(index))
  assert.notEqual(trackingKey(board),trackingKey({...board,boardType:'GN'}))
  for(const t of [stock,index,board,fund]) validateTrackingTarget(t)
  assert.equal(researchTarget(fund).kind,'stock')
  assert.equal(trackingAdjustment(fund),'NONE');assert.equal(trackingAdjustment(stock),'QFQ')
  assert.equal(trackingChartQuery(index,'WEEK').market,'SH')
  for(const t of [{...fund,code:'000001'},{...stock,market:'US'},{...stock,market:'SH'},{...stock,code:'100'},{...stock,code:300750},{...board,boardType:'OTHER'}]) assert.throws(()=>validateTrackingTarget(t))
})
test('cloud book validates without silently dropping corrupt groups or duplicate entries',()=>{
  assert.deepEqual(readTrackingBook(null),emptyTrackingBook())
  const b={version:1,revision:'r1',groups:[{id:'one',name:'研究',targets:[stock,index,board,fund]}]}
  const copy=readTrackingBook(b);copy.groups[0].name='changed';assert.equal(b.groups[0].name,'研究')
  for(const bad of [{...b,version:9},{...b,groups:[...b.groups,...b.groups]},{...b,groups:[{id:'one',name:'研究',targets:[stock,stock]}]}]) assert.throws(()=>readTrackingBook(bad))
  assert.throws(()=>readTrackingBook({...b,groups:Array.from({length:51},(_,i)=>({id:String(i),name:'组',targets:[]}))}))
})
test('expansion preserves every member and all board/direct sources, not a 200-row display page',async()=>{
  const members=Array.from({length:230},(_,i)=>({code:String(300000+i),market:0,name:`成员${i}`}))
  const second={...board,code:'881002',name:'行业乙'}
  const result=await expandTrackingGroup({id:'g',name:'组',targets:[{...stock,code:'300000'},board,second,index,fund]},async()=>({data:members,count:230}),new AbortController().signal)
  assert.equal(result.entries.length,234);assert.equal(result.issues.length,0)
  assert.deepEqual(result.entries.find(e=>e.target.code==='300000').sources,['直接追踪','881001-行业甲','881002-行业乙'])
  assert.ok(result.entries.some(e=>e.target.code==='300229'))
})
test('membership failure is explicit and malformed partial membership is never accepted',async()=>{
  for(const response of [{data:[],count:0},{data:[{code:'300001',market:0}],count:5},{data:[{code:'300001',market:0},{code:'bad',market:0}],count:2}]){
    const r=await expandTrackingGroup({id:'g',name:'组',targets:[board,stock]},async()=>response,new AbortController().signal)
    assert.equal(r.issues.length,1);assert.equal(r.entries.length,2)
  }
  const abort=new AbortController();abort.abort()
  await assert.rejects(expandTrackingGroup({targets:[board]},async()=>{throw new Error('not called')},abort.signal))
})
test('batch runs sequentially, keeps partial errors and continues after a failed target',async()=>{
  let active=0,max=0;const snapshots=[]
  const result=await analyzeTrackingEntries([stock,index,fund].map(target=>({target,sources:['直接']})),async t=>{
    active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,2));active--
    if(t.kind==='index') throw new Error('行情节点失败')
    return {rows:[{category:'DAY',...(t.kind==='fund'?{error:'无完整行情'}:{price:2})}]}
  },new AbortController().signal,rows=>snapshots.push(rows))
  assert.equal(max,1);assert.deepEqual(result.map(r=>r.state),['done','error','error'])
  assert.match(result[1].error,/节点/);assert.equal(result[2].study.rows.length,1)
  assert.equal(snapshots[0][0].state,'pending')
})
test('cancellation marks in-flight and unstarted rows, ignoring a late success',async()=>{
  const abort=new AbortController();let called=0
  const rows=await analyzeTrackingEntries([stock,index].map(target=>({target,sources:[]})),async()=>{called++;abort.abort();return {rows:[{}]}},abort.signal,()=>{})
  assert.equal(called,1);assert.deepEqual(rows.map(row=>row.state),['cancelled','cancelled']);assert.equal(rows[0].study,undefined)
})
test('group breadth counts only available periods, never treats failed targets as neutral evidence',()=>{
  const row={category:'DAY',direction_observation:{strict:{direction:'up'}},pairs:{macd:{fast:1,slow:2}},divergences:[{status:'confirmed'},{status:'confirmed'}]}
  const rows=[{target:stock,study:{rows:[row,{category:'WEEK',error:'missing'}]},state:'error'},{target:index,state:'cancelled'}]
  const [day,week]=trackingBreadth(rows,['DAY','WEEK'])
  assert.deepEqual(day,{category:'DAY',total:2,covered:1,penUp:1,penDown:0,aboveZero:1,belowZero:0,divergence:1})
  assert.equal(week.covered,0);assert.equal(week.total,2)
})
