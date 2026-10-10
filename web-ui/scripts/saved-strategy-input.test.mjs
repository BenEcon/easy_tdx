import test from 'node:test'
import assert from 'node:assert/strict'
import {savedStrategyInput,savedStrategyRequestId} from '../src/saved-strategy-input.ts'
const defaults={category:'DAY',adjust:'QFQ',startDate:'2020-01-06',endDate:'2026-10-09',cash:1000000,commission:.0003,minCommission:5,stampTax:.001,slippage:0,execution:'next_open'}
const record=()=>({id:'saved-1',name:'case',kind:'single',strategy:'ma_cross',params:{fast:5,slow:20},context:{symbol:'SH:510300',category:'MIN_30',adjust:'NONE',start_date:'2026-08-03',end_date:'2026-09-30'},trade_config:{cash:500,commission:.0002,min_commission:1.23,stamp_tax:0,slippage:.002,execution:'next_close'}})
test('saved single strategy restores market, period, adjustment and all execution costs exactly',()=>{
  const value=savedStrategyInput(record(),defaults,['ma_cross'])
  assert.deepEqual(value,{code:'510300',market:'SH',category:'MIN_30',adjust:'NONE',startDate:'2026-08-03',endDate:'2026-09-30',cash:500,commission:.0002,minCommission:1.23,stampTax:0,slippage:.002,execution:'next_close',strategy:'ma_cross',params:{fast:5,slow:20},warnings:[]})
  const original=record(), parsed=savedStrategyInput(original,defaults,['ma_cross'])
  original.params.fast=9;assert.equal(parsed.params.fast,5)
})
test('missing legacy fields disclose supplied defaults instead of claiming complete restoration',()=>{
  const old=record();old.context={symbol:'000001'};old.trade_config={}
  const value=savedStrategyInput(old,defaults,['ma_cross'])
  assert.equal(value.market,'SZ');assert.equal(value.adjust,'QFQ')
  assert.equal(value.warnings.length,11)
  assert.ok(value.warnings.some(w=>w.includes('复权方式')))
})
test('explicit contradictory market and unsupported instruments are not silently rewritten',()=>{
  for(const symbol of ['SZ:510300','SH:000001','BJ:000001','00001','SH:600000x','']){
    const input=record();input.context.symbol=symbol
    assert.throws(()=>savedStrategyInput(input,defaults,['ma_cross']),/标的/)
  }
})
test('invalid present fields are errors, not fallback defaults',()=>{
  for(const [scope,key,value] of [
    ['context','category','MIN_1'],['context','adjust',null],['context','start_date','2026-02-30'],
    ['context','start_date','2027-01-01'],['trade_config','cash',0],['trade_config','commission',.02],
    ['trade_config','min_commission',-1],['trade_config','stamp_tax','0'],['trade_config','slippage',Infinity],
    ['trade_config','execution','same_close'],['trade_config','cash',NaN],
  ]){const input=record();input[scope][key]=value;assert.throws(()=>savedStrategyInput(input,defaults,['ma_cross']),undefined,`${scope}.${key}`)}
  const unknown=record();unknown.strategy='removed';assert.throws(()=>savedStrategyInput(unknown,defaults,['ma_cross']),/不可用/)
  const multi=record();multi.kind='multi';assert.throws(()=>savedStrategyInput(multi,defaults,['ma_cross']),/单标的/)
  const bad=record();bad.params={fast:NaN};assert.throws(()=>savedStrategyInput(bad,defaults,['ma_cross']),/参数/)
})
test('saved links identify records only and cannot inject alternate execution context',()=>{
  assert.equal(savedStrategyRequestId({savedStrategyId:'a-1_b'}),'a-1_b')
  for(const q of [{},{savedStrategyId:['a','b']},{savedStrategyId:'../other'},...['autoRun','strategy','params','symbol','adjust','review','researchContext','editStrategyId'].map(key=>({savedStrategyId:'a', [key]:'x'}))])assert.throws(()=>savedStrategyRequestId(q))
})
