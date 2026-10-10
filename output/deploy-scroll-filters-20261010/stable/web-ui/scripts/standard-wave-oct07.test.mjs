import test from 'node:test'
import assert from 'node:assert/strict'
import { divergenceEvidence, waveCheckLine, waveComparisonLines, waveComparisonName } from '../src/divergence-evidence.ts'
import { macdPrompts } from '../src/divergence-marker.ts'

test('new standard evidence explains price, old blocker and independent special lifecycle', () => {
  const item = {bc:true,type:'macd_wave',direction:'down',status:'confirmed',
    signal_index:10,confirmed_index:11,curr_date:'2026-09-16',confirmed_date:'2026-09-17',
    evidence:{rule_version:2026100717,legacy_standard_passed:0,legacy_b_price_passed:0,legacy_dif_axis_passed:1},
    related_events:[{type:'macd_wave_special',signal_date:'2026-09-11',detected_date:'2026-09-11',status:'superseded',invalidated_date:'2026-09-15'}]}
  const lines=divergenceEvidence(item).join('\n')
  assert.match(lines,/C 最低 ≤ min\(A、B 最低\)/)
  assert.match(lines,/最多 5 根/)
  assert.match(lines,/不设幅度上限/)
  assert.match(lines,/旧版.*未通过.*B 触及或突破/)
  assert.match(lines,/关联特殊 AB.*已失效.*2026-09-15/)
  assert.doesNotMatch(lines,/有效 ABC 全程双线同侧/)
  assert.deepEqual(macdPrompts([item]),[item])
  assert.deepEqual(macdPrompts([{...item,status:'candidate',confirmed_index:null,confirmed_date:null}]),[])
})

test('new gates include counts, boundary and dates without undefined placeholder', () => {
  const text=waveCheckLine({gate:'b_dif_single_excursion',passed:false,
    values:{excursion_count:2,excursion_bars:3,maximum_bars:5},dates:{first_violation_index:'2026-09-03',last_violation_index:'2026-09-07'}})
  assert.match(text,/2 次、3 根/)
  assert.match(text,/2026-09-03 — 2026-09-07/)
  assert.doesNotMatch(text,/undefined/)
  assert.match(waveCheckLine({gate:'c_price_reaches_ab',passed:false,values:{a_price:20,b_price:18,c_price:19,direction:'down'}}),/B 极值 18.00/)
})

test('legacy comparisons retain old detected confirmed and invalidated dates', () => {
  const old={mode:'legacy_standard',dates:{known_index:'2026-09-17'},checks:[],closed:true,passed:false,
    events:[{signal_date:'2026-09-14',detected_date:'2026-09-14',status:'superseded',invalidated_date:'2026-09-15'}]}
  assert.match(waveComparisonName(old),/旧版标准/)
  assert.match(waveComparisonLines(old).join('\n'),/旧版记录.*首次提示 2026-09-14.*失效 2026-09-15/)
})
