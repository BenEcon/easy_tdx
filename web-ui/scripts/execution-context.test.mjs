import test from 'node:test'
import assert from 'node:assert/strict'
import {optimizationQuery,readOptimizationQuery,savedMultiInput,combineSavedSingles} from '../src/execution-context.ts'
const trade={cash:200000,commission:.0002,min_commission:1.23,stamp_tax:.0005,slippage:.002,execution:'next_close'}
const context={symbol:'SZ:300450',category:'DAY',adjust:'NONE',start_date:'2025-01-02',end_date:'2026-09-29'}
const single=()=>({id:'a',name:'a',kind:'single',strategy:'ma_cross',params:{fast:7,slow:31},context:{...context},trade_config:{...trade}})
const multi=()=>({kind:'multi',context:{cash:trade.cash,adjust:'NONE',items:[{...context,strategy:'ma_cross',params:{fast:7,slow:31}}]},trade_config:{...trade}})
test('optimization carries full execution and identity without live defaults',()=>{
  const req={...context,...trade},q=optimizationQuery(req,'ma_cross',{fast:7,slow:31});req.cash=999;req.adjust='HFQ'
  const value=readOptimizationQuery(q,['ma_cross']);assert.equal(value.cash,200000);assert.equal(value.adjust,'NONE');assert.equal(value.minCommission,1.23);assert.equal(value.stampTax,.0005);assert.equal(value.execution,'next_close');assert.deepEqual(value.warnings,[])
})
test('malformed, mixed, missing or conflicting optimization context never silently defaults',()=>{
  const valid=optimizationQuery({...context,...trade},'ma_cross',{fast:7,slow:31})
  for(const query of [{...valid,autoRun:'1'},{optimizationContext:'{}'},{optimizationContext:['abc']},{optimizationContext:'{'}])assert.throws(()=>readOptimizationQuery(query,['ma_cross']))
  for(const change of [r=>delete r.context.adjust,r=>r.context.symbol='SH:300450',r=>r.trade_config.cash=-1,r=>r.trade_config.execution='same_close',r=>r.version=2]){
    const raw=JSON.parse(valid.optimizationContext);change(raw);assert.throws(()=>readOptimizationQuery({optimizationContext:JSON.stringify(raw)},['ma_cross']))
  }
})
test('multi original replay preserves costs, slots and adjustment; extend changes only end dates',()=>{
  const source=multi(),before=JSON.stringify(source),original=savedMultiInput(source,['ma_cross'],'2026-10-10'),extended=savedMultiInput(source,['ma_cross'],'2026-10-10',true)
  assert.equal(JSON.stringify(source),before);assert.deepEqual(original.warnings,[])
  for(const [key,value] of Object.entries(trade))assert.equal(original.request[key],value)
  assert.equal(original.request.adjust,'NONE');assert.equal(original.request.items[0].end_date,'2026-09-29');assert.equal(extended.request.items[0].end_date,'2026-10-10')
  extended.request.items[0].end_date='2026-09-29';assert.deepEqual(extended.request,original.request)
})
test('multi rejects corrupt and incompatible slots without dropping or repairing any',()=>{
  for(const change of [r=>r.context.items.push(null),r=>r.context.items[0].symbol='SH:300450',r=>r.context.cash=3,r=>r.context.items[0].adjust='HFQ',r=>r.context.items[0].params=[],r=>r.trade_config.stamp_tax=-1,r=>r.kind='portfolio',r=>r.trade_config='corrupt',r=>r.context=[]]){
    const value=multi();change(value);assert.throws(()=>savedMultiInput(value,['ma_cross'],'2026-10-10'))
  }
})
test('legacy missing settings are disclosed with deterministic defaults, explicit invalid values rejected',()=>{
  const value=multi();delete value.context.adjust;delete value.context.items[0].adjust;delete value.trade_config.min_commission
  const parsed=savedMultiInput(value,['ma_cross'],'2026-10-10');assert.equal(parsed.request.min_commission,5);assert.equal(parsed.request.adjust,'QFQ');assert.equal(parsed.warnings.length,2)
  value.trade_config.min_commission=null;assert.throws(()=>savedMultiInput(value,['ma_cross'],'2026-10-10'))
})
test('combining equal-account singles preserves per-slot cash and costs; conflicts rejected not rewritten',()=>{
  const a=single(),b=single();b.context.symbol='SH:600699'
  const combined=combineSavedSingles([a,b],['ma_cross'],'2026-10-10');assert.equal(combined.request.cash,400000);assert.equal(combined.request.min_commission,1.23);assert.equal(combined.request.items.length,2)
  for(const key of Object.keys(trade)){
    const other=single();other.trade_config[key]=key==='execution'?'next_open':9;assert.throws(()=>combineSavedSingles([a,other],['ma_cross'],'2026-10-10'))
  }
  b.context.adjust='QFQ';assert.throws(()=>combineSavedSingles([a,b],['ma_cross'],'2026-10-10'))
})
