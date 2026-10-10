import test from 'node:test'
import assert from 'node:assert/strict'
import {activityMarketLabel,activityTargetLabel} from '../src/activity.ts'
import {activityTargetNames} from '../src/activity-target-names.ts'
import {queryAction} from '../src/query-origin.ts'

test('code labels use market-qualified identities and visible missing-name fallback',()=>{
  const names={'SZ:000001':'平安银行','SH:000001':'上证指数'}
  assert.equal(activityTargetLabel({key:'SZ:000001',code:'000001',market:'SZ'},names),'000001-平安银行')
  assert.equal(activityTargetLabel({key:'SH:000001',code:'000001',market:'SH'},names),'000001-上证指数')
  assert.equal(activityTargetLabel({key:'?:000001',code:'000001',market:'?'},names),'000001-名称待补全')
  assert.equal(activityMarketLabel('?'),'市场未记录')
})

test('name hydration is automatic, market-separated, bounded, and abort-aware',async()=>{
  const original=globalThis.fetch,calls=[]
  globalThis.fetch=async(url,init)=>{
    calls.push([String(url),init])
    if(String(url).includes('/board-mac/list')) return Response.json({data:[{code:'881001',name:'银行',market:90}]})
    const stocks=JSON.parse(init.body).stocks
    return Response.json({data:stocks.map(s=>({code:s.code,name:s.market==='SZ'?'平安银行':'示例证券'}))})
  }
  try {
    const targets=[{key:'SZ:000001',market:'SZ',code:'000001'},{key:'SH:000001',market:'SH',code:'000001'},
      {key:'BOARD:881001',market:'BOARD',code:'881001'},{key:'?:000001',market:'?',code:'000001'}]
    const result=await queryAction(true)(()=>activityTargetNames(targets,new AbortController().signal))
    assert.equal(result['SZ:000001'],'平安银行');assert.equal(result['SH:000001'],'上证指数')
    assert.equal(result['BOARD:881001'],'银行');assert.equal(result['?:000001'],undefined)
    assert.equal(calls.length,2)
    assert.ok(calls.every(([,init])=>init.headers?.['X-Query-Origin']!=='user'))
    calls.length=0
    const many=Array.from({length:205},(_,i)=>({key:`SZ:${String(300000+i)}`,code:String(300000+i),market:'SZ'}))
    const bounded=await activityTargetNames(many,new AbortController().signal)
    assert.equal(Object.keys(bounded).length,200);assert.equal(calls.length,10)
    assert.ok(calls.every(([,init])=>JSON.parse(init.body).stocks.length<=20))
    const c=new AbortController();c.abort();calls.length=0
    await activityTargetNames(targets,c.signal);assert.equal(calls.length,0)
    globalThis.fetch=async()=>{throw Error('offline')}
    assert.deepEqual(await activityTargetNames([targets[0]],new AbortController().signal),{})
  } finally {globalThis.fetch=original}
})
