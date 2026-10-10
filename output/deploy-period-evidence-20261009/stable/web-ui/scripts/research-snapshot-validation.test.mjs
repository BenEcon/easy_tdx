import test from 'node:test'
import assert from 'node:assert/strict'
import { validateResearchSnapshot } from '../src/research-snapshot-validation.ts'
const valid=()=>({schema:1,title:'测试',cutoff:'2026-10-05 15:00:00',target:{kind:'stock',code:'600699'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},
  charts:[{category:'DAY',metadata:{actual_adjust:'QFQ',observed_at:'2026-10-05 16:00:00'},bars:[{datetime:'2026-10-05 00:00:00',open:20,close:21,high:22,low:19}],result:{code:'600699',frequency:'day',bis:[],xds:[],zss:[],mmds:[],bcs:[]}}]})
test('snapshot import keeps original data and normalizes optional display metadata',()=>{
  const raw=valid();raw.note='<script>never execute</script>';raw.ruleVersions=[2026100414,null,'bad'];
  const parsed=validateResearchSnapshot(raw);assert.equal(parsed.note,raw.note);assert.deepEqual(parsed.ruleVersions,[2026100414]);assert.equal(parsed.charts,raw.charts);assert.equal(parsed.name,'测试');
})
test('reject invalid schema, periods, oversized arrays and impossible candle prices',()=>{
  for(const mutate of [v=>v.schema=2,v=>v.charts[0].category='MIN_120',v=>v.charts[0].bars[0].low=23,v=>v.charts[0].bars=Array(801).fill(v.charts[0].bars[0]),v=>v.charts[0].result.bis=[{low:1,high:2}],v=>v.layers=null]){
    const raw=valid();mutate(raw);assert.throws(()=>validateResearchSnapshot(raw));
  }
})
