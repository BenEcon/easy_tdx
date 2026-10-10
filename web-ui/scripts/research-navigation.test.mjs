import test from 'node:test'
import assert from 'node:assert/strict'
import { navigationTarget, researchNavigationQuery, readResearchNavigation, canOpenBacktest } from '../src/research-navigation.ts'

const entry = (target = navigationTarget({code:'000001',market:0,name:'平安银行'}).target) => ({target,category:'MIN_30',adjust:target.kind==='stock'?'HFQ':'NONE',count:600,source:'market'})
test('navigation preserves explicit stock/index/fund/board identity and parameters without auto run', () => {
  for (const [row, options, kind] of [
    [{code:'000001',market:1}, {}, 'index'], [{code:'000001',market:0}, {}, 'stock'],
    [{code:'399001',market:'sz'}, {}, 'index'], [{code:'510300',market:1}, {}, 'fund'],
    [{code:'159915',market:0}, {}, 'fund'], [{code:'920001',market:2}, {}, 'stock'],
    [{code:'880001',market:1}, {board:true,boardType:'HY'}, 'board'],
  ]) {
    const identified = navigationTarget(row, options)
    assert.equal(identified.target?.kind, kind, identified.error)
    const original = entry(identified.target), query = researchNavigationQuery(original)
    assert.deepEqual(readResearchNavigation(query), {value:original,error:''})
    assert.equal(query.autoRun, undefined)
    assert.equal(canOpenBacktest(original.target), ['stock','fund'].includes(kind))
  }
})
test('ambiguous identity is rejected rather than guessed or numeric code padded', () => {
  for (const row of [{code:1,market:0},{code:'000001'},{code:'SH000001',market:0},{code:'123456',market:0},{code:'000001',market:'unknown'}]) {
    assert.equal(navigationTarget(row).target, null)
  }
  assert.equal(navigationTarget({code:'000001'},{market:'SH'}).target.kind,'index')
  assert.equal(navigationTarget({code:'880001',market:1},{board:true,boardType:'ALL'}).target,null)
  assert.equal(navigationTarget({code:'880001',market:1,board_type:3},{board:true,boardType:'ALL'}).target.boardType,'GN')
})
test('query parser rejects incomplete, duplicate, incompatible and mixed-context values', () => {
  const query = researchNavigationQuery(entry())
  for (const patch of [
    {symbol:['000001','600000']},{market:''},{category:'bogus'},{count:'0600'},
    {count:'999999'}, {count:'300'}, {category:'MIN_1'}, {targetKind:'index'}, {boardType:'HY'}, {from:'tracking'},
    {researchContext:['v1']},{range:'historical'},{adjust:'invalid'},
    {autoRun:'1'},{review:'signal'},{asOf:'2026-10-09'}, {strategy:'ma_cross'},
    {params:'{}'}, {editStrategyId:'x'}, {startDate:'2020-01-01'},
    {savedStrategyId:'saved-1'}, {optimizationContext:'v1'}, {futureMode:'automatic'},
  ]) assert.ok(readResearchNavigation({...query,...patch}).error, JSON.stringify(patch))
  for(const key of Object.keys(query).filter(key=>key!=='researchContext')) {
    const missing={...query}; delete missing[key]
    assert.ok(readResearchNavigation(missing).error, key)
  }
  assert.deepEqual(readResearchNavigation({symbol:'000001'}), {value:null,error:''})
  const fund=entry(navigationTarget({code:'510300',market:'SH'}).target)
  assert.throws(()=>researchNavigationQuery({...fund,adjust:'QFQ'}),/不复权/)
})
