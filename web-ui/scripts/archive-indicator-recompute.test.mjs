import test from 'node:test'
import assert from 'node:assert/strict'
import { TECHNICAL_INDICATORS } from '../src/technical-indicators.ts'
import { freezeChartIndicators } from '../src/frozen-chart-indicators.ts'
import { archivedIndicatorSettings,projectRecomputedIndicators } from '../src/archive-indicator-recompute.ts'

const bars=Array.from({length:15},(_,i)=>({datetime:`2026-09-${String(i+1).padStart(2,'0')} 00:00:00`,open:10,close:10+i*.123456789,high:14,low:9,vol:100+i,amount:2000}))
test('all supported chart outputs preserve full precision, null warmups, style and instance order',()=>{
  for(const definition of TECHNICAL_INDICATORS){
    const config={type:definition.value,params:{...definition.defaultParams},rows:bars.map(()=>Object.fromEntries(definition.outputs.map(key=>[key,0])))}
    const before=freezeChartIndicators(bars,[5,17],[5],[config]),original=structuredClone(before),settings=archivedIndicatorSettings(before)
    const rows=bars.map((_,i)=>Object.fromEntries(definition.outputs.map((key,j)=>[key,i<4?null:i*.123456789+j])))
    const projected=projectRecomputedIndicators({averages:settings.averages.map(row=>({...row,values:bars.map((_,i)=>i<4?null:i*.987654321)})),indicators:[{type:config.type,params:config.params,rows}]},before,bars)
    assert.deepEqual(projected.indicators[0].series.map(series=>series.values),definition.outputs.map(key=>rows.map(row=>row[key])),definition.code)
    assert.deepEqual(projected.indicators[0].series.map(({values,...rest})=>rest),before.indicators[0].series.map(({values,...rest})=>rest))
    assert.deepEqual(before,original)
  }
})
