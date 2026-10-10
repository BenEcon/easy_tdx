import test from 'node:test'
import assert from 'node:assert/strict'
import { engineeringCompletion } from '../src/version-completion.ts'

function sample() {
  const part = {source_segment_indices:[3,4,5,6,7],direction:'down',start_index:13,end_index:33,
    start_value:110,end_value:93,known_index:135}
  const match = {rule:'exact_historical_engineering_completion_v1',movement_rule:'approved_mixed_macd_reverse_v1',
    status:'historical_engineering_match',movement_id:'movement:consolidation:L1:3:7',kind:'consolidation',level:1,
    ...part,known_index:140,as_of_index:170,opposite_id:'segment:8',natural_type_complete:false,eligible_for_recursive_input:false,
    macd_evidence:{area_ratio:.25,a_dif_extreme:-3,a_dea_extreme:-2.5,c_dif_extreme:-1.5,c_dea_extreme:-1.2}}
  const audit={engineering_completion:match,opposite_segment_index:8,opposite_known_index:140,
    start_is_extreme:true,end_is_extreme:true}
  return {part,audit}
}
const read=({part,audit})=>engineeringCompletion(part,audit,170)

test('historical engineering match retains original timing without claiming regrouping completion',()=>{
  const s=sample(), saved=structuredClone(s)
  assert.equal(read(s),s.audit.engineering_completion)
  assert.equal(read(s).known_index,140)
  assert.equal(read(s).natural_type_complete,false)
  assert.equal(read(s).eligible_for_recursive_input,false)
  assert.deepEqual(s,saved)
})

test('future, stale, mismatched or incomplete evidence fails closed',()=>{
  const changes=[
    m=>m.rule='other',m=>m.movement_rule='other',m=>m.status='complete',m=>m.level=2,
    m=>m.kind='trend',m=>m.direction='up',m=>m.movement_id='movement:consolidation:L1:4:8',
    m=>m.start_index++,m=>m.end_index++,m=>m.start_value++,m=>m.end_value++,
    m=>m.source_segment_indices=[4,5,6,7,8],m=>m.known_index=171,m=>m.known_index=134,
    m=>m.as_of_index=175,m=>m.opposite_id='segment:9',m=>m.natural_type_complete=true,
    m=>m.eligible_for_recursive_input=true,m=>m.macd_evidence.area_ratio=1,
    m=>m.macd_evidence.c_dea_extreme=NaN,m=>m.macd_evidence=undefined,
  ]
  for(const change of changes){const s=sample();change(s.audit.engineering_completion);assert.equal(read(s),null)}
  for(const change of [s=>s.audit.opposite_known_index=145,s=>s.audit.opposite_segment_index=9,
    s=>s.audit.end_is_extreme=false,s=>s.part.source_segment_indices=[3,4,4,6,7]]) {
    const s=sample();change(s);assert.equal(read(s),null)
  }
})

test('older snapshots and unmatched parts keep existing natural audit available',()=>{
  const s=sample()
  delete s.audit.engineering_completion
  assert.equal(read(s),null)
  s.audit.engineering_completion=null
  assert.equal(read(s),null)
})
