import test from 'node:test'
import assert from 'node:assert/strict'
import { componentCentres, componentSummary } from '../src/component-centres.ts'

function part() {
  return {component_kind:'trend_candidate',direction:'up',natural_type_complete:false,
    source_segment_indices:Array.from({length:9},(_,i)=>i),known_index:140,
    centre_chain:[{seed_segment_indices:[0,1,2],formed_index:110,low:0,high:10,zd:2,zg:8},
      {seed_segment_indices:[5,6,7],formed_index:135,low:15,high:22,zd:17,zg:20}]}
}
test('directed centre chain is candidate evidence, not completion',()=>{
  const p=part(), saved=structuredClone(p)
  assert.equal(componentSummary(p),'趋势候选 · 2 个同向分离中枢')
  assert.equal(componentCentres(p),p.centre_chain)
  assert.deepEqual(p,saved)
  p.direction='down'
  for(const c of p.centre_chain){[c.low,c.high]=[-c.high,-c.low];[c.zd,c.zg]=[-c.zg,-c.zd]}
  assert.equal(componentCentres(p),p.centre_chain)
})
test('touching, opposing, future, overlapping or malformed chains fail closed',()=>{
  const changes=[p=>p.centre_chain[1].low=10,p=>p.direction='down',p=>p.centre_chain[1].formed_index=141,
    p=>p.centre_chain[1].seed_segment_indices=[2,3,4],p=>p.centre_chain[1].seed_segment_indices=[8,9,10],
    p=>p.centre_chain[1].zg=p.centre_chain[1].zd,p=>p.centre_chain[1].zd=NaN,
    p=>p.component_kind='consolidation_candidate',p=>p.natural_type_complete=true,
    p=>p.centre_chain[1].formed_index=100,p=>p.centre_chain[1].seed_segment_indices=[5,7,8]]
  for(const change of changes){const p=part();change(p);assert.equal(componentCentres(p),null);assert.equal(componentSummary(p),'子走势结构待核验')}
})
test('single-centre and legacy components remain readable',()=>{
  const p=part();p.centre_chain.pop();p.component_kind='consolidation_candidate'
  assert.equal(componentSummary(p),'单中枢候选')
  delete p.centre_chain;delete p.component_kind
  assert.equal(componentSummary(p),'单中枢候选');assert.equal(componentCentres(p),null)
})
