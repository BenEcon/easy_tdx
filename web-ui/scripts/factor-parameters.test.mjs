import test from 'node:test'
import assert from 'node:assert/strict'
import {editableFactorParameters,selectedFactorParameters,parameterizedFactorName,factorParameterError,factorWarmupWarnings,resetFactorParameter,factorParameterUnit} from '../src/factor-parameters.ts'

test('dimensionless exponents are not presented as bar counts',()=>{
  assert.equal(factorParameterUnit('selected_observations'),'个下跌样本')
  assert.equal(factorParameterUnit('dimensionless'),'（无量纲）')
  assert.equal(factorParameterUnit('bars'),'根')
  assert.equal(factorParameterUnit('multiple'),'倍')
  assert.equal(factorParameterUnit(undefined),'根')
  assert.equal(factorParameterUnit('CNY'),'CNY')
})
test('filtered sample windows are never labelled as calendar periods',()=>{
  const d={name:'gtja191_149',display_name:'GTJA149',parameterized_title:'GTJA149',parameters:{window:{default:252,editable:true,unit:'selected_observations'}}}
  assert.match(parameterizedFactorName(d,{window:30}),/30个下跌样本/)
  assert.match(factorWarmupWarnings([d.name],[d],{[d.name]:{window:30}},300)[0],/30 个有效基准下跌样本/)
})

const factor=(name,window)=>({name,library:'qlib_alpha158',family:'MA',display_name:`均价收盘比 · ${window}周期`,parameters:{window:{default:window,editable:true,min:2,max:600}}})
const defs=[factor('alpha158_ma5',5),factor('alpha158_ma10',10)]
test('Alpha101 cross-library aliases normalize parameter keys and order',()=>{
  const spec=value=>({default:value,editable:true,min:1,max:500})
  const a={name:'alpha101_003',parameter_family:'gtja191:compound_105',parameter_aliases:{window:'corr'},parameters:{window:spec(10)}}
  const g={name:'gtja191_105',parameter_family:a.parameter_family,parameters:{corr:spec(10)}}
  assert.match(factorParameterError([a.name,g.name],[a,g],{}),/重复/)
  assert.equal(factorParameterError([a.name,g.name],[a,g],{[a.name]:{window:7}}),'')
  const b={name:'alpha101_002',parameter_family:'gtja191:compound_1',parameters:{lag:spec(2),corr:spec(6)}}
  const h={name:'gtja191_001',parameter_family:b.parameter_family,parameters:{corr:spec(6),lag:spec(1)}}
  assert.equal(factorParameterError([b.name,h.name],[b,h],{}),'')
  assert.match(factorParameterError([b.name,h.name],[b,h],{[b.name]:{lag:1}}),/重复/)
})
test('Alpha101 curvature threshold identity and warmup are declared',()=>{
  const a={name:'alpha101_049',parameter_family:'alpha101_price_curvature_threshold',warmup_limit:600,warmup_terms:[{offset:1,windows:['window','window']}],parameters:{window:{default:10,editable:true,min:1,max:500},threshold:{default:-.1,editable:true,integer:false,min:-10,max:0}}}
  const b={...a,name:'alpha101_051',parameters:{...a.parameters,threshold:{...a.parameters.threshold,default:-.05}}}
  assert.equal(factorParameterError([a.name,b.name],[a,b],{}),'')
  assert.match(factorParameterError([a.name,b.name],[a,b],{[a.name]:{threshold:-.05}}),/重复/)
  assert.match(factorWarmupWarnings([a.name],[a],{[a.name]:{window:30}},60)[0],/61 根/)
  assert.match(factorParameterError([a.name],[a],{[a.name]:{window:300}}),/601 根/)
  assert.equal(factorParameterUnit('价格单位/根'),'价格单位/根')
})
test('Alpha101 short custom mean still retains fixed price-lag dependency',()=>{
  const d={name:'alpha101_023',library:'alpha101',display_name:'Alpha101 023',warmup_bars:20,warmup_terms:[{offset:0,windows:['window']},{offset:3,windows:[]}],parameters:{window:{default:20,editable:true,min:1,max:500}}}
  assert.match(factorWarmupWarnings([d.name],[d],{[d.name]:{window:1}},2)[0],/3 根/)
  assert.deepEqual(factorWarmupWarnings([d.name],[d],{[d.name]:{window:1}},3),[])
  assert.match(factorWarmupWarnings([d.name],[d],{[d.name]:{window:30}},29)[0],/30 根/)
})
test('named GTJA dependency paths use maximum chain and all edited windows',()=>{
  const d={name:'gtja191_152',library:'gtja191',display_name:'GTJA 152',parameterized_title:'GTJA 152',warmup_bars:53,warmup_limit:600,warmup_terms:[{offset:0,windows:['lag','smooth','long','signal']}],parameters:Object.fromEntries(Object.entries({lag:9,smooth:9,short:12,long:26,signal:9}).map(([key,value])=>[key,{default:value,editable:true,min:1,max:600,label:key}]))}
  assert.match(factorWarmupWarnings([d.name],[d],{[d.name]:{lag:20,long:50,signal:10}},80)[0],/89 根/)
  assert.deepEqual(factorWarmupWarnings([d.name],[d],{[d.name]:{lag:20,long:50,signal:10}},89),[])
  assert.match(factorParameterError([d.name],[d],{[d.name]:{lag:300,long:300}}),/618 根/)
  assert.match(factorParameterError([d.name],[d],{[d.name]:{short:26}}),/短窗口/)
  assert.match(parameterizedFactorName(d,{long:50}),/lag 9.*long 50/)
  const branched={...d,warmup_terms:[{offset:-1,windows:['smooth','smooth']},{offset:1,windows:['long']}]}
  assert.match(factorWarmupWarnings([d.name],[branched],{[d.name]:{smooth:30}},50)[0],/59 根/)
  assert.match(factorWarmupWarnings([d.name],[branched],{[d.name]:{long:70}},50)[0],/71 根/)
  assert.equal(factorParameterError([d.name],[d],{[d.name]:{lag:NaN}}).length>0,true)
})
test('GTJA compound windows and cross-library identical mean ratios are explicit',()=>{
  const a={name:'gtja191_046',library:'gtja191',family:'four_mean_ratio',parameter_family:'gtja191:four_mean_ratio',warmup_bars:24,warmup_multiplier:8,warmup_offset:0,parameters:{window:{default:3,editable:true,min:1,max:75}}}
  const b={...a,name:'gtja191_189',warmup_bars:11,warmup_multiplier:2,warmup_offset:-1,parameters:{window:{default:6,editable:true,min:1,max:300}}}
  assert.match(factorWarmupWarnings([a.name],[a],{[a.name]:{window:30}},200)[0],/240 根/)
  assert.match(factorWarmupWarnings([b.name],[b],{[b.name]:{window:100}},160)[0],/199 根/)
  assert.ok(factorParameterError([a.name],[a],{[a.name]:{window:76}}))
  const mean={...a,name:'gtja191_065',family:'mean_ratio',parameters:{window:{default:6,editable:true,min:1,max:600}}}
  assert.match(factorParameterError([mean.name,defs[0].name],[mean,defs[0]],{[defs[0].name]:{window:6}}),/重复/)
})
test('parameter selection copies only active settings without mutating cached settings',()=>{
  const params={alpha158_ma5:{window:13},alpha158_ma10:{window:21}}
  const selected=selectedFactorParameters(['alpha158_ma5'],params)
  assert.deepEqual(selected,{alpha158_ma5:{window:13}})
  selected.alpha158_ma5.window=8
  assert.equal(params.alpha158_ma5.window,13)
  assert.equal(editableFactorParameters(defs[0]).length,1)
  assert.deepEqual(editableFactorParameters({parameters:{window:{editable:false}}}),[])
})

const windowSpec={default:20,editable:true,min:2,max:600,integer:true,label:'窗口'}
const base=[{name:'momentum_20d',parameter_family:'momentum',parameterized_title:'动量',display_name:'二十周期动量',warmup_bars:21,parameters:{window:windowSpec}},
  {name:'momentum_60d',parameter_family:'momentum',parameterized_title:'动量',display_name:'六十周期动量',warmup_bars:61,parameters:{window:{...windowSpec,default:60}}},
  {name:'boll_position',parameterized_title:'布林带相对位置',display_name:'布林带相对位置',warmup_bars:20,parameters:{window:windowSpec,std_multiplier:{default:2,editable:true,min:.1,max:10,integer:false,label:'标准差倍数'}}},
  {name:'macd_hist_signal',warmup_bars:20,parameters:{short:{...windowSpec,default:12},long:{...windowSpec,default:26},signal:{...windowSpec,default:9},scale_window:windowSpec}}]
test('builtin decimal multiplier, ordering, effective identity and actual labels',()=>{
  assert.equal(factorParameterError(['boll_position'],base,{boll_position:{std_multiplier:1.7}}),'')
  assert.match(parameterizedFactorName(base[2],{std_multiplier:1.7}),/窗口 20 \/ 标准差倍数 1.7/)
  for(const std_multiplier of [NaN,Infinity,0,11])assert.ok(factorParameterError(['boll_position'],base,{boll_position:{std_multiplier}}))
  assert.match(factorParameterError(['macd_hist_signal'],base,{macd_hist_signal:{short:26}}),/短窗口/)
  assert.match(factorParameterError(['momentum_20d','momentum_60d'],base,{momentum_20d:{window:60}}),/重复/)
})
test('reset only one parameter, retain other overrides without mutating input',()=>{
  const values={boll_position:{window:13,std_multiplier:1.7},momentum_20d:{window:7}}
  const reset=resetFactorParameter(values,'boll_position','window')
  assert.deepEqual(reset.boll_position,{std_multiplier:1.7})
  assert.equal(values.boll_position.window,13)
  assert.deepEqual(resetFactorParameter(reset,'boll_position','std_multiplier'),{momentum_20d:{window:7}})
})
test('history warning uses full effective warmup, not all parameters as rolling windows',()=>{
  assert.match(factorWarmupWarnings(['momentum_20d'],base,{momentum_20d:{window:600}},500)[0],/601 根/)
  assert.deepEqual(factorWarmupWarnings(['momentum_20d'],base,{momentum_20d:{window:600}},800),[])
  assert.match(factorWarmupWarnings(['macd_hist_signal'],base,{macd_hist_signal:{scale_window:300}},120)[0],/300 根/)
  assert.deepEqual(factorWarmupWarnings(['macd_hist_signal'],base,{macd_hist_signal:{long:600}},120),[])
  const alpha=[{...defs[0],warmup_bars:5}]
  assert.match(factorWarmupWarnings(['alpha158_ma5'],alpha,{alpha158_ma5:{window:600}},500)[0],/600 根/)
})
test('names and validation use actual windows; equivalent formula choices rejected',()=>{
  assert.equal(parameterizedFactorName(defs[0],{window:13}),'均价收盘比 · 13周期')
  assert.equal(parameterizedFactorName(defs[0]),'均价收盘比 · 5周期')
  assert.match(factorParameterError(defs.map(d=>d.name),defs,{alpha158_ma5:{window:10}}),/重复/)
  assert.equal(factorParameterError(defs.map(d=>d.name),defs,{alpha158_ma5:{window:13}}),'')
  for(const window of [NaN,0,1,13.2,601,Infinity])assert.match(factorParameterError(['alpha158_ma5'],defs,{alpha158_ma5:{window}}),/整数/)
  assert.match(factorParameterError(['alpha158_ma5'],defs,{alpha158_ma5:{bogus:13}}),/整数/)
})
