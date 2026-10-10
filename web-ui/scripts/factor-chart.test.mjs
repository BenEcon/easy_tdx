import test from 'node:test'
import assert from 'node:assert/strict'
import {factorChartOptions} from '../src/factor-chart.ts'
import {factorAxisValue} from '../src/factor-axis.ts'
import {factorTrackAxisValue} from '../src/factor-series-chart.ts'

test('single and multi-track axes share compact large units and distinct small ticks',()=>{
  for(const value of [0,0.003,0.006,0.009,0.012,-0.012,1e-7,180000000,99999,100000100,1e12,NaN]){
    assert.equal(factorChartOptions([],[]).yAxis.axisLabel.formatter(value),factorTrackAxisValue(value))
  }
  assert.equal(new Set([.003,.006,.009,.012,.015].map(v=>factorAxisValue(v))).size,5)
  assert.equal(factorAxisValue(180000000),'1.8亿')
  assert.equal(factorAxisValue(-12000),'-1.2万')
  assert.equal(factorAxisValue(1e12),'1万亿')
  assert.notEqual(factorAxisValue(100000100),factorAxisValue(100000200))
  assert.equal(factorAxisValue(.00003,true),'0.003%')
  assert.equal(factorAxisValue(Infinity),'—')
  const options=factorChartOptions(['2026-10-10T00:00:00','2026-10-10T10:30:00'],[])
  assert.equal(options.xAxis.axisLabel.formatter(options.xAxis.data[0]),'2026-10-10')
  assert.equal(options.xAxis.axisLabel.formatter(options.xAxis.data[1]),'2026-10-10 10:30:00')
  assert.equal(options.xAxis.data[0],'2026-10-10T00:00:00')
})

test('correlation uses its mathematical range; raw factors keep their own scale',()=>{
  const series=[{name:'秩相关',values:[1,null,1]}]
  const bounded=factorChartOptions(['a','b','c'],series,{correlation:true})
  assert.equal(bounded.yAxis.min,-1);assert.equal(bounded.yAxis.max,1)
  assert.equal(bounded.yAxis.scale,false)
  assert.equal(factorChartOptions([],series).yAxis.min,undefined)
})
test('tiny values remain visible and tooltip raw precision is not rounded',()=>{
  const tiny=0.000000123456789
  const auto=factorChartOptions([],[])
  assert.equal(auto.tooltip.valueFormatter(tiny),'1.23e-7')
  assert.equal(auto.yAxis.axisLabel.formatter(tiny),'1.23e-7')
  const raw=factorChartOptions([],[],{precision:'raw'})
  assert.equal(raw.tooltip.valueFormatter(tiny),String(tiny))
  for(const value of [NaN,Infinity,null,undefined])assert.equal(raw.tooltip.valueFormatter(value),'—')
})
test('percentage is presentation only, gaps and source values are preserved',()=>{
  const series=[{name:'分层收益',values:[0.00123456789,null,-0.01]}]
  const before=structuredClone(series)
  const opt=factorChartOptions(['a','b','c'],series,{percent:true,bar:true,precision:'raw'})
  assert.deepEqual(opt.series[0].data,series[0].values)
  assert.equal(opt.tooltip.valueFormatter(series[0].values[0]),`${series[0].values[0]*100}%`)
  assert.equal(opt.series[0].connectNulls,false)
  assert.deepEqual(opt.dataZoom,[])
  assert.deepEqual(series,before)
})
