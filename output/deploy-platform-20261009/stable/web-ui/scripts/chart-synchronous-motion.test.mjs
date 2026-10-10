import test from 'node:test'
import assert from 'node:assert/strict'
import { synchronousChartMotion, synchronizeChartSeries } from '../src/chart-synchronous-motion.ts'

test('all chart layers override independent animation and progressive rendering', () => {
  const rows=[[20,21,19,22]], points=[{coord:[0,19]}]
  const series=[{type:'candlestick',data:rows,large:true,progressive:3000,markPoint:{data:points,animation:true},markArea:{data:[]}},
    {type:'line',name:'笔',animationDurationUpdate:500,markLine:{data:[]}},
    {type:'bar',name:'MACD',animationDuration:260},{type:'line',name:'MA5'}]
  synchronizeChartSeries(series)
  for(const item of series){
    for(const [key,value] of Object.entries(synchronousChartMotion))assert.equal(item[key],value)
    assert.equal(item.progressive,0)
    for(const key of ['markPoint','markLine','markArea'])if(item[key])assert.equal(item[key].animation,false)
  }
  assert.equal(series[0].large,false)
  assert.equal(series[0].data,rows);assert.equal(series[0].markPoint.data,points)
  assert.deepEqual(rows,[[20,21,19,22]])
})
