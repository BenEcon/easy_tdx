import test from 'node:test'
import assert from 'node:assert/strict'
import {browseFactors,factorAvailabilityReason} from '../src/factor-catalog.ts'

const rows=[
  {name:'momentum_20d',library:'easy_tdx_builtin',display_name:'动量'},
  {name:'alpha158_rank20',library:'qlib_alpha158',display_name:'窗口价格百分位',family:'RANK'},
  {name:'alpha158_rank60',library:'qlib_alpha158',display_name:'窗口价格百分位',family:'RANK'},
  {name:'amount_relative_20',library:'easy_tdx_builtin',display_name:'成交额相对均值'},
  {name:'turnover_rate',library:'easy_tdx_builtin',alias_of:'amount_relative_20',display_name:'成交额相对均值'},
]
test('library navigation and Chinese/identifier/family search preserve full matching set',()=>{
  assert.equal(browseFactors(rows,'easy_tdx_builtin','').length,2)
  assert.equal(browseFactors(rows,'qlib_alpha158','百分位').length,2)
  assert.equal(browseFactors(rows,'all','rank20')[0].name,'alpha158_rank20')
  assert.equal(browseFactors(rows,'qlib_alpha158','RANK').length,2)
  assert.equal(browseFactors(rows,'qlib_alpha158','不存在').length,0)
  assert.equal(browseFactors(rows,'all','turnover_rate').length,1)
  assert.equal(browseFactors(rows,'easy_tdx_builtin','',['turnover_rate']).length,3)
})

test('availability is evaluated by adjustment and period without mutating selections',()=>{
  const row={name:'alpha158_vwap0',available:true,evaluation_available:true,supported_adjustments:['NONE'],supported_categories:['DAY','MIN_30'],adjustment_unavailable_reason:'仅不复权'}
  assert.equal(factorAvailabilityReason(row,'NONE'),'')
  assert.equal(factorAvailabilityReason(row,'QFQ'),'仅不复权')
  assert.equal(factorAvailabilityReason(row,'HFQ','DAY',true),'仅不复权')
  assert.equal(factorAvailabilityReason(row,'NONE','MIN_30',true),'')
  assert.match(factorAvailabilityReason(row,'NONE','WEEK'),/周期/)
  assert.equal(factorAvailabilityReason({...row,evaluation_available:false,evaluation_unavailable_reason:'未验收'},'NONE','DAY',true),'未验收')
  const selected=['alpha158_vwap0']
  assert.equal(browseFactors([{...row,library:'qlib_alpha158'}],'qlib_alpha158','vwap',selected).length,1)
  assert.deepEqual(selected,['alpha158_vwap0'])
})
