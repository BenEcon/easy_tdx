import test from 'node:test'
import assert from 'node:assert/strict'
import { visibleMixedCover, sourceRole } from '../src/mixed-sources.ts'

const ids = Array.from({length: 9}, (_, i) => i)
function sample() {
  return {rule:'indivisible_source_cover_v1',interpretation_id:'case:v1',as_of_index:150,
    source_segment_indices:ids.slice(),status:'covered',natural_type_complete:false,
    eligible_for_recursive_input:false,joint_regrouping_required:false,conflicts:[],
    blocks:[{kind:'extension_proof',proof_id:'extension:L2:0:8',level:2,
      source_segment_indices:ids.slice(),known_index:140,low:2,high:10,natural_type_complete:false,
      crosses_role_boundary:false,role_spans:[{role:'pending_tail',source_segment_indices:ids.slice()}]}]}
}
const read = d => visibleMixedCover(d,'case:v1',ids,150,151)

test('whole proof validated without mutation, and cross-role ownership remains visible', () => {
  const d=sample(), before=structuredClone(d)
  assert.equal(read(d),d); assert.deepEqual(d,before)
  d.blocks[0].role_spans=[{role:'part_2',source_segment_indices:ids.slice(0,3)},{role:'pending_tail',source_segment_indices:ids.slice(3)}]
  d.blocks[0].crosses_role_boundary=true;d.joint_regrouping_required=true
  assert.equal(read(d),d)
})
test('stale, future, duplicated, incomplete, falsely completed and mismatched sources rejected', () => {
  const changes=[d=>d.rule='old',d=>d.interpretation_id='case:v2',d=>d.as_of_index=151,
    d=>d.blocks[0].known_index=151,d=>d.blocks.push(d.blocks[0]),d=>d.blocks[0].source_segment_indices.pop(),
    d=>d.natural_type_complete=true,d=>d.eligible_for_recursive_input=true,d=>d.blocks[0].natural_type_complete=true,
    d=>d.blocks[0].role_spans[0].role='completed',d=>d.blocks[0].role_spans[0].source_segment_indices.pop(),
    d=>d.blocks[0].proof_id='extension:L3:0:8',d=>d.blocks[0].level=3,d=>d.blocks[0].high=NaN,
    d=>d.blocks[0].low=20,d=>d.blocks[0].crosses_role_boundary=true,d=>d.joint_regrouping_required=true]
  for(const change of changes){ const d=sample();change(d);assert.equal(read(d),null) }
  assert.equal(read(undefined),null)
  for(const count of [0,150,NaN,Infinity]) assert.equal(visibleMixedCover(sample(),'case:v1',ids,150,count),null)
})
test('base runs cannot masquerade as proofs or own multiple provisional regions', () => {
  const d=sample(), b=d.blocks[0]; b.kind='base_run';b.level=0;b.proof_id=null
  assert.equal(read(d),d)
  b.level=2;assert.equal(read(d),null)
})
test('blocked covers show full conflicts, never fabricated flattened blocks', () => {
  const d=sample();d.status='blocked';d.blocks=[];d.joint_regrouping_required=true
  d.conflicts=[{reason:'proof_crosses_window',proof_id:'proof',source_segment_indices:[...ids,9],known_index:145}]
  assert.equal(read(d),d)
  d.blocks=sample().blocks;assert.equal(read(d),null)
  d.blocks=[];d.conflicts[0].known_index=160;assert.equal(read(d),null)
})
test('labels retain provisional scope', () => {
  assert.equal(sourceRole('part_0'),'A 分区')
  assert.equal(sourceRole('retained_prefix'),'保留前缀')
  assert.equal(sourceRole('unknown'),'归属待核验')
})
