import test from 'node:test'
import assert from 'node:assert/strict'
import { visibleRegroupingCase, regroupingReason, regroupingStatus } from '../src/regrouping-versions.ts'

function sample() {
  return { rule: 'causal_regrouping_versions_v1', cases: [{ candidate_id: 'expansion:0:5',
    as_of_index: 185, formation_known_index: 150, current_revision_id: 'expansion:0:5:v2',
    revisions: [150,170].map((known, i) => ({id: `expansion:0:5:v${i+1}`, version:i+1,
      supersedes:i ? 'expansion:0:5:v1' : null, known_index:known,
      natural_type_complete:false, eligible_for_recursive_input:false})) }] }
}

test('matching versions are selected by case identity without mutation', () => {
  const data = sample(), before = structuredClone(data)
  assert.equal(visibleRegroupingCase(data, 'expansion:0:5',186),data.cases[0])
  assert.deepEqual(data,before)
  assert.equal(visibleRegroupingCase(data,'missing',186),null)
})

test('future snapshots, wrong rules, incomplete chains and duplicate cases are rejected', () => {
  assert.equal(visibleRegroupingCase(undefined,'expansion:0:5',186),null)
  for (const count of [0,185,150,NaN,Infinity,185.5]) assert.equal(visibleRegroupingCase(sample(),'expansion:0:5',count),null)
  const mutations = [d => d.rule='unknown', d => d.cases.push(d.cases[0]),
    d => d.cases[0].current_revision_id='stale',d => d.cases[0].revisions=[],
    d => d.cases[0].formation_known_index=180,
    d => d.cases[0].revisions[1].known_index=150,
    d => d.cases[0].revisions[1].known_index=200,
    d => d.cases[0].revisions[1].version=3,
    d => d.cases[0].revisions[1].id='wrong:v2',
    d => d.cases[0].revisions[1].supersedes=null,
    d => d.cases[0].revisions[1].eligible_for_recursive_input=true]
  for(const mutate of mutations) {
    const data=sample(); mutate(data)
    assert.equal(visibleRegroupingCase(data,'expansion:0:5',186),null)
  }
})

test('labels never confuse endpoint consistency or higher-centre proof with completion', () => {
  assert.match(regroupingStatus('endpoint_consistent_draft'),/自然完成待证/)
  assert.match(regroupingStatus('requires_higher_level_inputs'),/等待混合层级重组/)
  assert.equal(regroupingStatus('unknown'),'状态待核验')
  assert.equal(regroupingReason('endpoint_conflicts_resolved'),'新证据消除端点冲突')
  assert.equal(regroupingReason('unknown'),'变化原因待核验')
  assert.match(regroupingReason('start_boundary_regrouping'), /前缀保留待核验/)
})

function shiftedSample() {
  const data = sample(), item = data.cases[0], range = (a,b) => Array.from({length:b-a},(_,i)=>a+i)
  data.rule = 'causal_regrouping_versions_v2'
  Object.assign(item,{origin_start_segment_index:6,start_anchor_segment_indices:range(6,14),pending_segment_indices:[22,23]})
  Object.assign(item.revisions[0],{source_segment_indices:range(6,21),retained_prefix_segment_indices:[],prefix_role:'unresolved_prior_sources',start_change:null})
  Object.assign(item.revisions[1],{source_segment_indices:range(11,22),retained_prefix_segment_indices:range(6,11),prefix_role:'unresolved_prior_sources',start_change:{previous_start_segment_index:6,current_start_segment_index:11,detached_segment_indices:range(6,11),reincorporated_segment_indices:[]}})
  return data
}

test('v2 keeps the detached prefix and v1 remains readable', () => {
  const data=shiftedSample(), before=structuredClone(data)
  assert.equal(visibleRegroupingCase(data,'expansion:0:5',186),data.cases[0])
  assert.deepEqual(data,before)
  assert.ok(visibleRegroupingCase(sample(),'expansion:0:5',186))
})

test('v3 supports trend search while retaining the same ownership guards', () => {
  const data=shiftedSample();data.rule='causal_regrouping_versions_v3'
  assert.equal(visibleRegroupingCase(data,'expansion:0:5',186),data.cases[0])
  data.cases[0].pending_segment_indices=[24]
  assert.equal(visibleRegroupingCase(data,'expansion:0:5',186),null)
})

test('missing, duplicated, misattributed or silently completed prefix is rejected', () => {
  const changes = [c=>delete c.origin_start_segment_index, c=>c.start_anchor_segment_indices=[6,7],
    c=>c.start_anchor_segment_indices=[6,7,9,11],c=>c.pending_segment_indices=[23],
    c=>delete c.revisions[1].retained_prefix_segment_indices,
    c=>c.revisions[1].retained_prefix_segment_indices=[6,7,8,9],
    c=>c.revisions[1].retained_prefix_segment_indices=[6,7,8,9,10,11],
    c=>c.revisions[1].prefix_role='completed_trend',
    c=>c.revisions[1].start_change=null,
    c=>c.revisions[1].start_change.previous_start_segment_index=7,
    c=>c.revisions[1].start_change.current_start_segment_index=12,
    c=>c.revisions[1].start_change.detached_segment_indices=[6,7],
    c=>c.revisions[1].start_change.reincorporated_segment_indices=[6]]
  for (const change of changes) {
    const data=shiftedSample();change(data.cases[0])
    assert.equal(visibleRegroupingCase(data,'expansion:0:5',186),null)
  }
})

test('reincorporation is recorded explicitly instead of erasing detached history', () => {
  const data=shiftedSample(), c=data.cases[0], old=structuredClone(c.revisions[1])
  c.revisions.push({...structuredClone(old),id:'expansion:0:5:v3',version:3,supersedes:old.id,known_index:180,
    source_segment_indices:Array.from({length:18},(_,i)=>6+i),retained_prefix_segment_indices:[],
    start_change:{previous_start_segment_index:11,current_start_segment_index:6,detached_segment_indices:[],reincorporated_segment_indices:[6,7,8,9,10]}})
  c.current_revision_id='expansion:0:5:v3';c.pending_segment_indices=[]
  assert.ok(visibleRegroupingCase(data,'expansion:0:5',186))
  assert.deepEqual(c.revisions[1],old)
})
