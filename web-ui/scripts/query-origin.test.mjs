import test from 'node:test'
import assert from 'node:assert/strict'
import {queryAction,queryIntentHeaders} from '../src/query-origin.ts'
import {fetchMarketStat,fetchStockNames,submitBacktestTask,fetchTask,fetchBarSnapshot} from '../src/api.ts'

const origin=()=>queryIntentHeaders()['X-Query-Origin']
test('query defaults to system, manual intent is synchronous and explicit',()=>{
  assert.equal(origin(),'system')
  queryAction(true)(()=>{
    assert.equal(origin(),'user')
    queryAction(false)(()=>assert.equal(origin(),'system'))
    assert.equal(origin(),'user')
  })
  assert.equal(origin(),'system')
  assert.throws(()=>queryAction(true)(()=>{throw Error('network')}))
  assert.equal(origin(),'system')
})

test('direct bar snapshot fetch preserves explicit intent, including failed requests',async()=>{
  const original=globalThis.fetch,seen=[]
  globalThis.fetch=async(_url,init)=>{
    seen.push(new Headers(init?.headers).get('X-Query-Origin'))
    return new Response(JSON.stringify({detail:'QA no data'}),{status:503})
  }
  try{
    await assert.rejects(fetchBarSnapshot('SZ','000001','DAY',600,'QFQ'))
    await assert.rejects(queryAction(true)(()=>fetchBarSnapshot('SZ','000001','DAY',600,'QFQ')))
    assert.deepEqual(seen,['system','user'])
  }finally{globalThis.fetch=original}
})
test('pending manual requests do not mark concurrent automatic work or async continuations',async()=>{
  let release
  const wait=new Promise(resolve=>{release=resolve})
  const seen=[]
  const result=queryAction(true)(async()=>{
    seen.push(origin())
    await wait
    seen.push(origin())
  })
  assert.equal(origin(),'system')
  await queryAction(false)(async()=>{seen.push(origin());await Promise.resolve();seen.push(origin())})
  release();await result
  assert.deepEqual(seen,['user','system','system','system'])
  assert.equal(queryAction(true)(origin),'user')
})

test('API dispatch tags manual queries but excludes automatic name lookup and task polling',async()=>{
  const original=globalThis.fetch,seen=[]
  globalThis.fetch=async(url,init)=>{
    seen.push({url:String(url),origin:new Headers(init?.headers).get('X-Query-Origin')})
    return new Response(JSON.stringify({data:[],task_id:'qa'}),{status:200})
  }
  try{
    await fetchMarketStat()
    await queryAction(true)(()=>fetchMarketStat())
    await queryAction(true)(()=>fetchStockNames([{market:'SZ',code:'000001'}]))
    await queryAction(true)(()=>submitBacktestTask({}))
    await fetchTask('qa')
    assert.deepEqual(seen.map(row=>row.origin),['system','user',null,'system','user',null])
    assert.match(seen[2].url,/quotes/)
    assert.match(seen[3].url,/symbol-info/)
    assert.equal(origin(),'system')
  }finally{globalThis.fetch=original}
})
