import test from 'node:test'
import assert from 'node:assert/strict'
import { divergenceEvidence, waveFailureSummary, waveDiagnosticLines, waveCheckLine, waveComparisonName, waveComparisonLines } from '../src/divergence-evidence.ts'

test('special diagnostics identify each A indicator witness rather than the price witness', () => {
  const line = waveCheckLine({gate:'special_dea_a_segment_extreme', passed:true,
    values:{previous_value:-3.5,current_value:-1.2},
    dates:{previous_index:'2026-01-06',current_index:'2026-01-10'}})
  assert.match(line, /A 段指标极值 → B 价格极值当根/)
  assert.match(line, /A 指标极值 2026-01-06/)
  assert.ok(!line.includes('未识别'))
})

test('nonstandard DEA axis gate remains explicit without an improvement requirement', () => {
  const check = { gate: 'dea_zero_axis_without_improvement', passed: true,
    values: { a_extreme: -.88, c_extreme: -.99, direction: 'down' } }
  const line = waveCheckLine(check)
  assert.match(line, /DEA/)
  assert.match(line, /零轴/)
  assert.ok(!line.includes('未识别'))
  const lines = waveDiagnosticLines({family: 'nonstandard', checks: [check], dates: {}, rejections: []}).join('\n')
  assert.match(lines, /只取消 DEA 极值改善/)
  assert.match(lines, /零轴/)
})

test('DEA tolerance discloses research threshold, precise deviation and near-zero fallback', () => {
  const check = { gate: 'dea_extreme_tolerance', passed: true, values: {
    a_extreme: .0601532455, c_extreme: .0626991424, worsening_ratio: .0423235166,
    strict_passed: false, tolerance_enabled: true } }
  const item = { mode: 'dea_tolerance', closed: false, dates: {}, checks: [check] }
  assert.match(waveComparisonName(item), /DEA 容差 5%/)
  const lines = waveComparisonLines(item).join('\n')
  for (const text of ['4.2324%', '0.060153 → 0.062699', '未作有效性验证', '不生成 M1', 'C 尚未结束', '不等于严格改善']) assert.ok(lines.includes(text))
  assert.ok(!lines.includes('未识别'))
  check.values.tolerance_enabled = false
  check.values.worsening_ratio = null
  assert.match(waveCheckLine(check), /禁用相对容差/)
  assert.match(waveFailureSummary({checks: [{...check, passed: false}]}), /DEA 超出 5% 容差/)
})

test('wave evidence separates effective A from original wave and local pivots', () => {
  const lines = divergenceEvidence({ type: 'macd_wave', evidence: { a_axis_trimmed: 1 },
    intervals: { original_a_start: '2025-09-30', original_a_end: '2025-12-05', a_start: '2025-11-14' } })
  assert.ok(lines.some(s => s.includes('不要求最近局部极值')))
  assert.ok(lines.some(s => s.includes('2025-09-30') && s.includes('2025-11-14')))
  assert.ok(!lines.some(s => s.includes('同时核验最近局部极值')))
})

test('rounded equal line extrema disclose the precise failed values and witness times', () => {
  const check = { gate: 'dea_extreme_and_zero_axis', passed: false,
    values: { a_extreme: .0601532455, c_extreme: .0626991424 },
    dates: { a_extreme_index: '2026-09-21 11:30', c_extreme_index: '2026-09-22 11:30' } }
  const line = waveCheckLine(check)
  assert.ok(line.includes('0.06 → 0.06'))
  assert.ok(line.includes('0.060153 → 0.062699'))
  assert.ok(line.includes('2026-09-22 11:30'))
  const lines = divergenceEvidence({ type: 'macd_wave', evidence: {}, intervals: {},
    invalidated_date: '2026-09-22 11:30', failure_audit: { dates: { known_index: '2026-09-22 11:30' }, checks: [check] } })
  assert.ok(lines.some(l => l.includes('首次失效时的数值')))
  assert.ok(lines.some(l => l.includes('0.060153 → 0.062699')))
  assert.ok(lines.some(l => l.includes('各自整个比较段') && l.includes('两条线须同时改善')))
})

test('comparisons are explicitly research only and preserve B/C axis checks', () => {
  const item = { mode: 'full_a_equal_price', passed: false, closed: false, dates: {},
    checks: [{ gate: 'dif_whole_bc_zero_axis', passed: false,
      values: { first_violation_value: .0033728, violation_count: 5 },
      dates: { first_violation_index: '2026-09-04 11:00' } }] }
  assert.equal(waveComparisonName(item), '完整 A ＋ 等高／等低')
  assert.equal(waveFailureSummary(item), 'B、C 内 DIF 触轴或跨轴')
  const lines = waveComparisonLines(item)
  assert.ok(lines.some(l => l.includes('不生成 M1 或交易信号')))
  assert.ok(lines.some(l => l.includes('C 尚未结束')))
  assert.ok(lines.some(l => l.includes('2026-09-04 11:00') && l.includes('0.003373')))
})

test('unformed candidate shows Chinese gates, two-decimal values and rejection dates', () => {
  const record = { closed: true, dates: { known_index: '2026-01-08', c_start: '2026-01-06', c_end: '2026-01-07' },
    checks: [{ gate: 'shrinking_same_colour_area', passed: false, values: { a_area: 1.123456, c_area: 3.23456 } }],
    rejections: [{ from_date: '2026-01-06', through_date: '2026-01-08', gates: ['shrinking_same_colour_area'] }] }
  assert.equal(waveFailureSummary(record), 'C 同色柱面积未小于比较 A')
  const lines = waveDiagnosticLines(record)
  assert.ok(lines.some(s => s.includes('1.12 → 3.23')))
  assert.ok(lines.some(s => s.includes('拦截记录 2026-01-06 — 2026-01-08')))
  assert.ok(!lines.join('').includes('shrinking_same_colour_area'))
})

test('new nonstandard audit explicitly uses full A and first-formed reverse evidence explains gaps', () => {
  const nonstandard = divergenceEvidence({type:'macd_wave_nonstandard', direction:'down',
    evidence:{rule_version:20261004,a_full_comparison:1},intervals:{
      original_a_start:'2026-09-22',original_a_end:'2026-09-29',a_start:'2026-09-22',a_end:'2026-09-29'}}).join('\n')
  assert.match(nonstandard,/面积、价格和 DIF 极值均取完整 A/)
  assert.match(nonstandard,/只取 B 内 DIF、DEA/)
  const waiting=divergenceEvidence({type:'macd_wave_special',status:'candidate',direction:'up',
    evidence:{reverse_pen_waiting:1,reverse_pen_wait_code:4,reverse_pen_observed_gap:0,reverse_pen_required_gap:1}}).join('\n')
  assert.match(waiting,/间距不足（0 \/ 要求 1）/)
})
