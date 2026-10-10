import test from 'node:test'
import assert from 'node:assert/strict'
import { validateResearchSnapshot } from '../src/research-snapshot-validation.ts'
import { freezeChartIndicators } from '../src/frozen-chart-indicators.ts'
const valid=()=>({schema:1,title:'测试',cutoff:'2026-10-05 15:00:00',target:{kind:'stock',code:'600699'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},
  charts:[{category:'DAY',metadata:{actual_adjust:'QFQ',observed_at:'2026-10-05 16:00:00'},bars:[{datetime:'2026-10-05 00:00:00',open:20,close:21,high:22,low:19}],result:{code:'600699',frequency:'day',bis:[],xds:[],zss:[],mmds:[],bcs:[]}}]})
test('snapshot import keeps original data and normalizes optional display metadata',()=>{
  const raw=valid();raw.note='<script>never execute</script>';raw.ruleVersions=[2026100414,null,'bad'];
  const parsed=validateResearchSnapshot(raw);assert.equal(parsed.note,raw.note);assert.deepEqual(parsed.ruleVersions,[2026100414]);assert.equal(parsed.charts,raw.charts);assert.equal(parsed.name,'测试');
})
test('reject invalid schema, periods, oversized arrays and impossible candle prices',()=>{
  for(const mutate of [v=>v.schema=2,v=>v.charts[0].category='MIN_999',v=>v.charts[0].bars[0].low=23,v=>v.charts[0].bars=Array(8001).fill(v.charts[0].bars[0]),v=>v.charts[0].result.bis=[{low:1,high:2}],v=>v.layers=null,v=>v.charts.push(v.charts[0])]){
    const raw=valid();mutate(raw);assert.throws(()=>validateResearchSnapshot(raw));
  }
})
test('cloud archives retain larger frozen windows and all supported distinct periods',()=>{
  const raw=valid(), chart=raw.charts[0]
  chart.bars=Array.from({length:801},(_,i)=>({...chart.bars[0],datetime:new Date(Date.UTC(2020,0,i+1)).toISOString().replace('T',' ').slice(0,19)}))
  raw.charts=['DAY','WEEK','MONTH','MIN_1','MIN_5','MIN_15','MIN_30','MIN_60','MIN_120'].map(category=>({...chart,category}))
  const parsed=validateResearchSnapshot(raw)
  assert.equal(parsed.charts.length,9);assert.equal(parsed.charts[0].bars.length,801)
  assert.equal(parsed.charts,raw.charts)
})
test('import keeps valid frozen outputs and rejects mismatched frozen data instead of recomputing',()=>{
  const raw=valid(),chart=raw.charts[0]
  chart.frozenIndicators=freezeChartIndicators(chart.bars,[5],[5],[])
  assert.equal(validateResearchSnapshot(raw).charts[0].frozenIndicators,chart.frozenIndicators)
  chart.frozenIndicators.dates[0]='2026-10-04 00:00:00'
  assert.throws(()=>validateResearchSnapshot(raw),/冻结指标不完整/)
})
