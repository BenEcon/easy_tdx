import test from 'node:test'
import assert from 'node:assert/strict'
import { versionCompletion } from '../src/version-completion.ts'
import { completionReason } from '../src/expansion-evidence.ts'

function sample() {
  const part={source_segment_indices:[0,1,2],direction:'up',start_index:1,end_index:13,
    start_value:1,end_value:10,low:1,high:10,known_index:110}
  const revision={id:'case:v2',version:2,known_index:110,parts:[part],higher_proof_ids:[],source_segment_indices:[0,1,2],retained_prefix_segment_indices:[]}
  const audit={rule:'version_bound_completion_audit_v1',interpretation_id:'case:v2',as_of_index:115,
    natural_type_complete:false,eligible_for_recursive_input:false,blocking_reasons:['same_level_completion_unproven'],
    parts:[{part_index:0,source_segment_indices:[0,1,2],start_extreme:1,end_extreme:10,start_is_extreme:true,end_is_extreme:true,
      opposite_segment_index:3,opposite_known_index:115,natural_type_complete:false,
      status:'awaiting_same_level_completion',blocking_reasons:['same_level_completion_unproven'],
      opposite_evidence:{segment_index:3,direction:'down',start_index:13,end_index:17,known_index:115,
        start_value:10,end_value:5,source_part_index:null}}]}
  return {revision,audit}
}
const read = ({revision,audit})=>versionCompletion(audit,revision,115,116)
test('exact current revision accepts only its own evidence without mutation',()=>{
  const s=sample(), before=structuredClone(s)
  assert.equal(read(s),s.audit);assert.deepEqual(s,before)
})
test('old partition, stale version, future evidence and false completion are rejected',()=>{
  const changes=[s=>s.audit.interpretation_id='case:v1',s=>s.audit.as_of_index=110,
    s=>s.audit.parts[0].source_segment_indices=[1,2,3],s=>s.audit.parts[0].part_index=1,
    s=>s.audit.parts[0].opposite_evidence.known_index=120,s=>s.audit.parts[0].opposite_evidence.source_part_index=0,
    s=>s.audit.natural_type_complete=true,s=>s.audit.eligible_for_recursive_input=true,
    s=>s.audit.parts[0].natural_type_complete=true,s=>s.audit.blocking_reasons=[],
    s=>s.audit.parts.push(s.audit.parts[0]),s=>s.audit.parts[0].status='completed',
    s=>s.audit.parts[0].start_is_extreme=false,s=>s.audit.parts[0].end_extreme=NaN]
  for(const change of changes){const s=sample();change(s);assert.equal(read(s),null)}
  const s=sample();assert.equal(versionCompletion(undefined,s.revision,115,116),null)
  assert.equal(versionCompletion(s.audit,s.revision,115,115),null)
})
test('historical audit cannot import a later opposite segment',()=>{
  const s=sample();s.audit.as_of_index=110
  assert.equal(versionCompletion(s.audit,s.revision,110,116),null)
  Object.assign(s.audit.parts[0],{opposite_segment_index:null,opposite_known_index:null,opposite_evidence:null,status:'awaiting_opposite_lower_unit'})
  assert.equal(versionCompletion(s.audit,s.revision,110,116),s.audit)
})
test('empty partitions and higher-proof priority retain explicit blockers',()=>{
  const s=sample();s.revision.parts=[];s.audit.parts=[];s.revision.higher_proof_ids=['proof']
  assert.equal(read(s),null)
  s.audit.blocking_reasons.push('no_current_partition','higher_proof_requires_regrouping')
  assert.equal(read(s),s.audit)
  s.revision.retained_prefix_segment_indices=[0];assert.equal(read(s),null)
  s.audit.blocking_reasons.push('retained_prefix_unresolved');assert.equal(read(s),s.audit)
})
test('new blockers use Chinese labels without calling prerequisites completion',()=>{
  for(const r of ['no_current_partition','higher_proof_requires_regrouping','retained_prefix_unresolved','source_cover_conflict','indivisible_proof_crosses_boundary'])
    assert.doesNotMatch(completionReason(r),/未识别/)
  assert.match(completionReason('same_level_completion_unproven'),/缺少/)
})
