import fs from 'node:fs'
import assert from 'node:assert/strict'
import { freezeChartIndicators } from '../../web-ui/src/frozen-chart-indicators.ts'
import { projectRecomputedIndicators } from '../../web-ui/src/archive-indicator-recompute.ts'
const matrix=JSON.parse(fs.readFileSync(new URL('./matrix.json',import.meta.url),'utf8'))
let instances=0,series=0,points=0
for(const {settings,output} of matrix.cases){
  const original=freezeChartIndicators(matrix.bars,settings.averages.map(row=>row.period),settings.averages.filter(row=>row.enabled).map(row=>row.period),output.indicators)
  const projected=projectRecomputedIndicators(output,original,matrix.bars)
  assert.deepEqual(projected,original)
  instances+=original.indicators.length
  series+=original.indicators.reduce((sum,item)=>sum+item.series.length,0)
  points+=original.indicators.reduce((sum,item)=>sum+item.series.reduce((n,row)=>n+row.values.length,0),0)
}
console.log(JSON.stringify({instances,series,points,averages:'exact full precision',warmup:'null preserved'}))
