import test from 'node:test'
import assert from 'node:assert/strict'
import {
  expansionStatus, partitionSelection, completionStatus, completionReason,
  evidencePrice, evidenceRange, candidateAudit, matchingPartAudit,
  oppositeEvidence,
} from '../src/expansion-evidence.ts'

test('all candidate states distinguish eligibility from completed natural types', () => {
  assert.equal(expansionStatus('awaiting_centre_exit'), '等待两中枢退出')
  assert.equal(expansionStatus('requires_higher_level_inputs'), '需要更高层级输入')
  assert.equal(expansionStatus('no_three_range_partition'), '未找到有效三段切分')
  assert.match(expansionStatus('partition_found_awaiting_type_completion'), /自然完成待证/)
  assert.equal(expansionStatus('future_status'), '状态待核验')
})

const oppositeSample = () => ({
  candidate: {source_segment_indices: [17,18,19,20,21,22,23,24,25],
    parts: [{source_segment_indices:[17,18,19]}, {source_segment_indices:[20,21,22]}, {source_segment_indices:[23,24,25]}]},
  part: {source_segment_indices:[17,18,19], end_index:13, end_value:20, known_index:100, direction:'up'},
  audit: {opposite_segment_index:20, opposite_known_index:105, opposite_evidence:{
    segment_index:20, direction:'down', start_index:13, end_index:17, known_index:105,
    start_value:20, end_value:15, source_part_index:1}},
})

test('opposite geometry identifies reused next-part evidence, including nonzero source IDs', () => {
  const {candidate, part, audit}=oppositeSample()
  const before=structuredClone(audit)
  assert.match(oppositeEvidence(candidate,part,audit,106).sourceLabel,/属于分区 B.*不是额外独立/)
  assert.deepEqual(audit,before)
})

test('external opposite geometry is not added to candidate membership', () => {
  const {candidate,part,audit}=oppositeSample()
  part.source_segment_indices=[23,24,25]
  audit.opposite_segment_index=26
  Object.assign(audit.opposite_evidence,{segment_index:26,source_part_index:null})
  assert.match(oppositeEvidence(candidate,part,audit,106).sourceLabel,/候选来源之后.*不计入/)
  assert.equal(candidate.source_segment_indices.length,9)
})

test('missing, stale, misattributed or future opposite geometry is not displayed as matched', () => {
  const {candidate,part,audit}=oppositeSample()
  for(const patch of [{segment_index:21},{known_index:104},{start_index:12},{end_index:13},
    {start_value:19},{end_value:21},{direction:'up'},{source_part_index:2},{source_part_index:null},
    {end_index:NaN},{known_index:Infinity},{end_value:Infinity}]) {
    assert.equal(oppositeEvidence(candidate,part,{...audit,opposite_evidence:{...audit.opposite_evidence,...patch}},106),null)
  }
  assert.equal(oppositeEvidence(candidate,part,audit,105),null)
  assert.equal(oppositeEvidence(candidate,part,undefined,106),null)
  assert.equal(oppositeEvidence(candidate,part,{...audit,opposite_evidence:null},106),null)
  candidate.parts[2].source_segment_indices.unshift(20)
  assert.equal(oppositeEvidence(candidate,part,audit,106),null)
})

test('preferred endpoints are never called completed types; conflicts are retained', () => {
  assert.equal(partitionSelection('endpoint_consistent_preferred'), '优先选择端点一致的切分')
  assert.match(partitionSelection('geometric_fallback_with_conflicts'), /保留几何切分及冲突/)
  assert.match(partitionSelection(), /未提供/)
  assert.match(partitionSelection(null), /未提供/)
  assert.match(partitionSelection('future'), /未提供/)
})

test('opposite base turn is not same-level completion', () => {
  assert.equal(completionStatus('endpoint_conflict'), '端点与区间极值冲突')
  assert.equal(completionStatus('awaiting_opposite_lower_unit'), '等待反向基础线段')
  assert.match(completionStatus('awaiting_same_level_completion'), /同级别完成待证/)
  assert.match(completionStatus(), /未提供或不匹配/)
  assert.match(completionStatus('future'), /未提供或不匹配/)
  assert.match(completionReason('same_level_completion_unproven'), /缺少同级别自然走势完成证明/)
  assert.match(completionReason('start_not_directional_extreme'), /起点/)
  assert.match(completionReason('end_not_directional_extreme'), /终点/)
  assert.match(completionReason('no_confirmed_opposite_lower_unit'), /尚无已确认/)
  assert.match(completionReason('future'), /未识别/)
})

test('price formatting preserves zero and boundary contact, guards non-finite values', () => {
  assert.equal(evidencePrice(0), '0.00')
  assert.equal(evidencePrice(1.234567), '1.23')
  assert.equal(evidencePrice(-1.235), '-1.24')
  for (const value of [null, undefined, NaN, Infinity, -Infinity]) assert.equal(evidencePrice(value), '未提供')
  assert.equal(evidenceRange([14, 14]), '14.00–14.00')
  assert.equal(evidenceRange([0, 1.234]), '0.00–1.23')
  for (const value of [null, [], [1], [2, 1], [1, 2, 3], [NaN, 1]]) assert.equal(evidenceRange(value), '未形成')
})

test('candidate audit joins by identity, not response order', () => {
  const wrong = { candidate_id: 'expansion:1:4', parts: [] }
  const wanted = { candidate_id: 'expansion:17:21', parts: [] }
  const data = { completion_audits: [wrong, wanted] }
  assert.equal(candidateAudit(data, { id: wanted.candidate_id }), wanted)
  assert.equal(candidateAudit(data, { id: 'missing' }), undefined)
  assert.equal(candidateAudit(undefined, { id: wanted.candidate_id }), undefined)
  assert.equal(candidateAudit({}, { id: wanted.candidate_id }), undefined)
})

test('part audit must match ordinal AND exact raw source IDs, including shifted IDs', () => {
  const part = { source_segment_indices: [17, 18, 19] }
  const correct = { part_index: 0, source_segment_indices: [17, 18, 19] }
  const stale = { part_index: 0, source_segment_indices: [17, 18, 19, 20, 21] }
  const swapped = { part_index: 1, source_segment_indices: [17, 18, 19] }
  const audit = { parts: [stale, swapped, correct] }
  const before = structuredClone(audit)
  assert.equal(matchingPartAudit(audit, part, 0), correct)
  assert.equal(matchingPartAudit({ parts: [stale, swapped] }, part, 0), undefined)
  assert.equal(matchingPartAudit(undefined, part, 0), undefined)
  assert.deepEqual(audit, before)
})
