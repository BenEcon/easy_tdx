import test from 'node:test'
import assert from 'node:assert/strict'
import { freezeChartIndicators, validateFrozenChartIndicators, frozenIndicatorSeries, frozenAverageSeries } from '../src/frozen-chart-indicators.ts'
import { buildIndicatorSeries, TECHNICAL_INDICATORS } from '../src/technical-indicators.ts'

const bars=Array.from({length:31},(_,i)=>({datetime:`2026-01-${String(i+1).padStart(2,'0')} 00:00:00`,open:10+i,high:12+i,low:9+i,close:11+i*.123456789,vol:100+i,amount:1000,is_closed:i!==30}))
const numeric=series=>series.data.map(v=>v===null?null:typeof v==='number'?v:v.value)

test('warmup null, missing and invalid indicator values never become invented zeroes',()=>{
  const values=[null,undefined,'',false,'1.2',NaN,Infinity,0,1.234567891]
  const series=buildIndicatorSeries('rsi',bars.slice(0,values.length),values.map(RSI=>({RSI})))
  assert.deepEqual(series[0].data,[null,null,null,null,null,null,null,0,1.234567891])
  assert.deepEqual(buildIndicatorSeries('fk',bars.slice(0,3),[{FK:false},{FK:true},{FK:null}])[0].data,[0,1,null])
})

test('freeze all supported indicator outputs, warmup holes, volume averages and exact numerical precision',()=>{
  for(const definition of TECHNICAL_INDICATORS){
    const item={type:definition.value,params:{...definition.defaultParams},rows:bars.map((_,i)=>Object.fromEntries(definition.outputs.map((key,j)=>[key,i<j?undefined:(i-j)*.123456789])))}
    const frozen=freezeChartIndicators(bars,[5,10,17],[5,17],[item])
    const original=buildIndicatorSeries(item.type,bars,item.rows)
    assert.deepEqual(frozen.indicators[0].series.map(s=>s.values),original.map(numeric),definition.code)
    assert.deepEqual(frozenIndicatorSeries(frozen.indicators[0],bars).map(numeric),original.map(numeric),definition.code)
    assert.equal(frozen.averages[0].values[0],null)
    assert.equal(frozen.averages[0].values[4],bars.slice(0,5).reduce((n,b)=>n+b.close,0)/5)
    assert.deepEqual(frozen.averages.map(ma=>ma.enabled),[true,false,true])
    assert.deepEqual(JSON.parse(JSON.stringify(frozen)),frozen)
  }
})

test('frozen playback keeps captured values despite different current prices and never queries APIs',t=>{
  t.mock.method(globalThis,'fetch',()=>{throw Error('unexpected recalculation')})
  const source=structuredClone(bars),rows=source.map((_,i)=>({MACD_DIF:i*.0123456789,MACD_DEA:i*.023456789,MACD_HIST:-i*.03456789}))
  const frozen=freezeChartIndicators(source,[5],[5],[{type:'volume',params:{},rows:[]},{type:'macd',params:{SHORT:12,LONG:26,M:9},rows}])
  const captured=structuredClone(frozen)
  source[0].close=500;source[0].vol=999999;rows[3].MACD_DEA=999
  assert.deepEqual(frozen,captured)
  assert.deepEqual(frozenAverageSeries(frozen)[0].data,captured.averages[0].values)
  assert.deepEqual(frozenIndicatorSeries(frozen.indicators[0],source).map(numeric),captured.indicators[0].series.map(s=>s.values))
  assert.deepEqual(frozenIndicatorSeries(frozen.indicators[1],source).map(numeric),captured.indicators[1].series.map(s=>s.values))
})

test('malformed or mismatched frozen values fail closed, never fall back to recomputation',()=>{
  const valid=freezeChartIndicators(bars,[5],[5],[{type:'volume',params:{},rows:[]}])
  for(const mutate of [v=>v.schema=2,v=>v.dates.reverse(),v=>v.averages[0].values.pop(),v=>v.averages[0].values[0]=NaN,
    v=>v.averages.push(v.averages[0]),v=>v.indicators[0].series[0].values.pop(),v=>v.indicators[0].params={N:'5'},
    v=>v.indicators[0].series[0].type='custom',v=>v.indicators[0].series[0].color='url(example)',v=>v.indicators[0].bounds=[2,1]]){
    const bad=structuredClone(valid);mutate(bad);assert.throws(()=>validateFrozenChartIndicators(bad,bars),/冻结指标不完整/)
  }
})
