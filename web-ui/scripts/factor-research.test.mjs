import test from 'node:test'
import assert from 'node:assert/strict'
import {factorValue,factorStatisticsLabel,sortedFactorRows,factorSearchKey,factorAliasVisible} from '../src/factor-research.ts'
test('statistics version is frozen provenance, never inferred as the current version',()=>{
  assert.equal(factorStatisticsLabel({statistics_version:'factor-cross-section-numerics-v2'}),'factor-cross-section-numerics-v2')
  for(const value of [undefined,null,7,''])assert.match(factorStatisticsLabel({statistics_version:value}),/旧版原档未记录/)
  assert.equal(factorStatisticsLabel({statistics_version:'future-v5'}),'future-v5')
})
test('factor glossary accepts standard abbreviations with spaces or underscores',()=>{
  for(const term of ['RankIC','Rank IC','rank_ic','rank-ic'])assert.equal(factorSearchKey(term),'rankic')
  assert.equal(factorSearchKey(' 秩相关 '),'秩相关')
})
test('factor missing values never become valid zero',()=>{
  for(const value of [null,undefined,NaN,Infinity,'0','',false])assert.equal(factorValue(value),'—')
  assert.equal(factorValue(0),'0.00');assert.equal(factorValue(.0345,true),'3.45%')
})
test('factor ranking is stable, non-mutating and missing-last in both directions',()=>{
  const rows=[{code:'c',v:null},{code:'b',v:2},{code:'a',v:2},{code:'d',v:0}]
  const original=structuredClone(rows)
  assert.deepEqual(sortedFactorRows(rows,'v',-1).map(r=>r.code),['a','b','d','c'])
  assert.deepEqual(sortedFactorRows(rows,'v',1).map(r=>r.code),['d','a','b','c'])
  assert.deepEqual(rows,original)
})
test('small factor values do not round to fake zeros; raw precision keeps original number',()=>{
  assert.equal(factorValue(.000012345),'1.23e-5')
  assert.equal(factorValue(-.000012345),'-1.23e-5')
  assert.equal(factorValue(.0000002,true),'2.00e-5%')
  assert.equal(factorValue(.01234567890123,false,'raw'),'0.01234567890123')
  assert.equal(factorValue(0,false,'raw'),'0')
  assert.equal(factorValue(null,false,'raw'),'—')
})
test('compatibility aliases are only shown for exact legacy lookup or active selection',()=>{
  const alias={name:'turnover_rate',alias_of:'amount_relative_20'}
  for(const query of ['', '成交额', 'turnover', 'amount_relative_20'])assert.equal(factorAliasVisible(alias,query),false)
  assert.equal(factorAliasVisible(alias,'turnover_rate'),true)
  assert.equal(factorAliasVisible(alias,'Turnover Rate'),true)
  assert.equal(factorAliasVisible(alias,'',['turnover_rate']),true)
  assert.equal(factorAliasVisible({name:'amount_relative_20'},''),true)
})
