import test from 'node:test'
import assert from 'node:assert/strict'
import { centreState, centreEvidence, segmentEvidence, segmentsConnected } from '../src/structure-evidence.ts'
import { confirmationPosition } from '../src/confirmation-replay.ts'

test('centre evidence distinguishes fixed core, outer range and candidate expansion', () => {
  const lines = centreEvidence({ zd: 10, zg: 12, dd: 8, gg: 14,
    formed_date: '2026-01-10', seed_segments: [0, 1, 2], member_segments: [0, 1, 2, 3],
    relation_at_formation: 'expansion_candidate',
    transitions: [{ state: 'departed', segment_index: 4, known_date: '2026-01-15' }],
  })
  assert.ok(lines.includes('固定核心：10.00–12.00；外围：8.00–14.00'))
  assert.ok(lines.includes('初始三段：1、2、3'))
  assert.ok(lines.some(line => line.includes('尚非已确认高级别中枢')))
  assert.ok(lines.includes('2026-01-15 · 线段 5 · 离开待回试'))
  assert.equal(centreState('exited'), '回试确认退出')
})

test('segment evidence includes source prices and reverse proof with one-based labels', () => {
  const feature = {low: 10.1234, high: 12.5678, pen_indices: [1, 3], high_pen: 1, low_pen: 3}
  const lines = segmentEvidence({end_date: '2026-01-05', confirmed_date: '2026-01-10',
    evidence: {case: 'gap_reverse_fractal', start_pen: 0, end_pen: 2, supporting_pen: 8,
      features: [feature], reverse_features: [feature]},
  })
  assert.ok(lines.some(line => line.includes('极值端点：2026-01-05；确认时间：2026-01-10')))
  assert.ok(lines.some(line => line.includes('来源笔 2、4；高点来自笔 2，低点来自笔 4')))
  assert.ok(lines.some(line => line.startsWith('反向确认元素 1：10.12–12.57')))
  assert.ok(lines.some(line => line.includes('最后一笔：9')))
})

test('missing legacy evidence does not invent confirmation', () => {
  assert.match(segmentEvidence({})[0], /未提供/)
  assert.equal(centreState(), '辅助重叠区')
})

test('special inclusion explains boundary exception without labelling it an ordinary fractal', () => {
  const lines = segmentEvidence({end_date: '2026-01-05',
    evidence: {case: 'boundary_inclusion_break', special_inclusion: true, start_pen: 0, end_pen: 2},
  })
  assert.match(lines[0], /第 71、78 课/)
  assert.match(lines[0], /分界两侧不合并/)
})

test('centre relation history distinguishes current candidate from original separation', () => {
  const lines = centreEvidence({zd: 18, zg: 20, dd: 14, gg: 25,
    relation_at_formation: 'separated_up', relation_current: 'expansion_candidate',
    relation_history: [{relation: 'expansion_candidate', known_date: '2026-05-20',
      previous_centre: 0, envelope_overlap: [14, 14], both_exited: false}],
  })
  assert.ok(lines.includes('形成时与前中枢的关系：外围向上分离'))
  assert.ok(lines.some(line => line.startsWith('当前关系：扩展候选')))
  assert.ok(lines.some(line => line.includes('外围交集 14.00–14.00；后中枢尚未确认退出')))
  assert.ok(lines.some(line => line.includes('退出不代表趋势结束')))
})

test('confirmation replay translates raw indices without date matching', () => {
  assert.equal(confirmationPosition(0, 800), 1)
  assert.equal(confirmationPosition(0, 800, true), null)
  assert.equal(confirmationPosition(426, 800), 427)
  assert.equal(confirmationPosition(426, 800, true), 426)
  assert.equal(confirmationPosition(799, 800), 800)
})

test('unknown, invalid or out-of-snapshot confirmations have no replay target', () => {
  for (const index of [undefined, null, -1, 800, 1.5, NaN, Infinity]) {
    assert.equal(confirmationPosition(index, 800), null)
    assert.equal(confirmationPosition(index, 800, true), null)
  }
  assert.equal(confirmationPosition(0, 0), null)
})

test('connection badge validates shared time, price and alternating direction', () => {
  const up = {start_date: '2026-01-01', end_date: '2026-01-10', direction: 'up', start_value: 10, end_value: 20}
  const down = {start_date: '2026-01-10', end_date: '2026-01-20', direction: 'down', start_value: 20, end_value: 12}
  assert.equal(segmentsConnected([up, down]), true)
  assert.equal(segmentsConnected([up, {...down, start_date: '2026-01-11'}]), false)
  assert.equal(segmentsConnected([up, {...down, start_value: 21}]), false)
  assert.equal(segmentsConnected([up, {...down, direction: 'up'}]), false)
  assert.equal(segmentsConnected([]), false)
})
