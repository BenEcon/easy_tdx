import test from 'node:test'
import assert from 'node:assert/strict'
import { alignCandleBody, installCandleAlignment } from '../src/candlestick-alignment.ts'
import * as echarts from 'echarts/core'
import { CandlestickChart, LineChart } from 'echarts/charts'
import { GridComponent, DataZoomComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'

echarts.use([CandlestickChart, LineChart, GridComponent, DataZoomComponent, SVGRenderer, installCandleAlignment])

test('body is symmetric around the unchanged wick across widths and fractional positions', () => {
  for (const width of [2, 2.5, 3, 4, 7.25, 12]) for (const center of [99.5, 100.5, 101.5]) {
    const layout = {ends: [[99.5,20],[100.5,20],[100.5,30],[99.5,30],[center,10],[center,20],[center,40],[center,30]],brushRect:{x:99,y:10,width,height:30}}
    const original = structuredClone(layout)
    alignCandleBody(layout, width)
    assert.equal((layout.ends[0][0]+layout.ends[1][0])/2, center)
    assert.deepEqual(layout.ends.slice(4), original.ends.slice(4))
    assert.deepEqual(layout.ends.map(p=>p[1]), original.ends.map(p=>p[1]))
    assert.equal(layout.brushRect.x+layout.brushRect.width/2,center)
    assert.ok(layout.ends.slice(0,4).every(p=>p[0]%1===.5))
    const once = structuredClone(layout)
    alignCandleBody(layout, width)
    assert.deepEqual(layout, once)
  }
})

test('horizontal candles preserve every price coordinate', () => {
  const layout = {ends:[[20,99.5],[20,100.5],[30,100.5],[30,99.5],[10,99.5],[20,99.5],[40,99.5],[30,99.5]]}
  const prices=layout.ends.map(p=>p[0])
  alignCandleBody(layout,3,1)
  assert.equal((layout.ends[0][1]+layout.ends[1][1])/2,99.5)
  assert.deepEqual(layout.ends.map(p=>p[0]),prices)
})

test('missing or non-finite candle layouts are left untouched', () => {
  alignCandleBody(undefined,2)
  const missing={ends:[]}; alignCandleBody(missing,2); assert.deepEqual(missing,{ends:[]})
  const invalid={ends:Array.from({length:8},()=>[NaN,2])}, copy=structuredClone(invalid)
  alignCandleBody(invalid,2); assert.deepEqual(invalid,copy)
})

test('native ECharts layout remains centred after resize, zoom and data replacement', () => {
  const chart=echarts.init(null,null,{renderer:'svg',ssr:true,width:390,height:400})
  const rows=Array.from({length:150},(_,i)=>[20+(i%5)/10,20.4+(i%5)/10,19,22])
  rows[5]=[20,20,19,22] // doji
  rows[6]=[20.4,20,19,22] // falling
  chart.setOption({animation:false,grid:{left:58,right:28},xAxis:{type:'category',data:rows.map((_,i)=>String(i))},yAxis:{type:'value',scale:true},dataZoom:[{type:'inside',start:0,end:100}],series:[{type:'candlestick',data:rows,barMinWidth:2,barMaxWidth:12}]})
  function check() {
    const data=chart.getModel().getSeriesByIndex(0).getData()
    assert.ok(data.count()>0)
    for(let i=0;i<data.count();i++) {
      const points=data.getItemLayout(i).ends
      assert.ok(points.flat().every(Number.isFinite))
      assert.equal((points[0][0]+points[1][0])/2,points[4][0])
      assert.equal((points[2][0]+points[3][0])/2,points[6][0])
      assert.equal(points[4][0],points[6][0])
    }
  }
  try {
    check()
    for(const width of [320,390,430,844,1440]) { chart.resize({width,height:400}); check() }
    chart.dispatchAction({type:'dataZoom',start:70,end:100}); check()
    chart.dispatchAction({type:'dataZoom',start:35,end:55}); check()
    chart.setOption({series:[{data:rows.map(([o,c,l,h])=>[o+1,c+1,l+1,h+1])}]}); check()
    assert.deepEqual(chart.getOption().series[0].data,rows.map(([o,c,l,h])=>[o+1,c+1,l+1,h+1]))
  } finally { chart.dispose() }
})

test('zooming out of large-data line mode restores centred candle bodies', () => {
  const chart=echarts.init(null,null,{renderer:'svg',ssr:true,width:390,height:400})
  const rows=Array.from({length:1000},()=>[20,21,19,22])
  try {
    chart.setOption({animation:false,xAxis:{type:'category',data:rows.map((_,i)=>String(i))},yAxis:{type:'value'},dataZoom:[{type:'inside'}],series:[{type:'candlestick',data:rows,barMinWidth:2,barMaxWidth:12,large:true,largeThreshold:600}]})
    assert.equal(chart.getModel().getSeriesByIndex(0).pipelineContext.large,true)
    chart.dispatchAction({type:'dataZoom',start:95,end:100})
    const series=chart.getModel().getSeriesByIndex(0), data=series.getData()
    assert.equal(series.pipelineContext.large,false)
    assert.ok(data.count()>0)
    for(let i=0;i<data.count();i++) {
      const p=data.getItemLayout(i).ends
      assert.ok(p.flat().every(Number.isFinite))
      assert.equal((p[0][0]+p[1][0])/2,p[4][0])
      assert.deepEqual(data.getItemGraphicEl(i).shape.points,p)
    }
  } finally { chart.dispose() }
})
