import test from 'node:test'
import assert from 'node:assert/strict'
import { divergenceMarker, macdPrompts, visibleDivergences } from '../src/divergence-marker.ts'
import { divergenceName, divergenceEvidence } from '../src/divergence-evidence.ts'

test('direction, family and lifecycle have independent marker styles', () => {
  for (const direction of ['up', 'down']) {
    for (const type of ['macd', 'macd_wave', 'qs', 'pz']) {
      const base = { bc: true, type, direction }
      const pending = divergenceMarker({ ...base, status: 'candidate' })
      const confirmed = divergenceMarker({ ...base, status: 'confirmed' })
      assert.equal(pending.symbol, type === 'macd' ? 'circle' : 'diamond')
      assert.equal(pending.itemStyle.color, 'transparent')
      assert.equal(pending.itemStyle.borderType, 'dashed')
      assert.equal(confirmed.itemStyle.color, direction === 'up' ? '#61dfa0' : '#cf8ff5')
      assert.equal(confirmed.itemStyle.borderType, 'solid')
      assert.equal(divergenceMarker({ ...base, status: 'superseded' }), null)
      assert.equal(divergenceMarker({ ...base, bc: false }), null)
    }
  }
})

test('no-C dual-line remains a circle and fills only on first reverse-pen confirmation', () => {
  for (const direction of ['up', 'down']) {
    const base = { bc: true, type: 'macd', direction, status: 'candidate', signal_index: 10,
      evidence: { rule_version: 20261004, special_no_c: 1, price: 19, previous_price: 20, dif: -.5, previous_dif: -1,
        dea: -.7, previous_dea: -1.2 } }
    const pending = divergenceMarker(base)
    assert.equal(pending.symbol, 'circle')
    assert.equal(pending.symbolSize, 9)
    assert.equal(pending.itemStyle.color, 'transparent')
    assert.equal(pending.itemStyle.borderType, 'dashed')
    assert.match(divergenceName(base), /双线/)
    assert.match(divergenceEvidence(base).join('\n'), /最近局部高／低点/)
    assert.match(divergenceEvidence(base).join('\n'), /不作为标准波段背离或 M1/)
    const complete = { ...base, status: 'confirmed', confirmed_index: 18,
      evidence: { ...base.evidence, reverse_pen_start: 10, reverse_pen_end: 14, reverse_pen_confirmed: 18 } }
    assert.equal(divergenceMarker(complete).itemStyle.color, direction === 'up' ? '#61dfa0' : '#cf8ff5')
    assert.equal(divergenceMarker(complete).itemStyle.borderType, 'solid')
    assert.deepEqual(macdPrompts([complete]), [])
    for (const item of [{ ...base, preliminary_index: 12 }, { ...complete, confirmed_index: 10 },
      { ...complete, evidence: { ...complete.evidence, reverse_pen_start: 9 } },
      { ...complete, evidence: base.evidence }]) {
      assert.equal(divergenceMarker(item).itemStyle.color, 'transparent')
    }
    assert.equal(divergenceMarker({ ...base, status: 'superseded' }), null)
    assert.equal(divergenceMarker({ ...base, evidence: {} }).symbol, 'circle')
    assert.equal(divergenceMarker({ ...base, type: 'macd_wave' }).symbolSize, 9)
  }
})

test('M1 is restricted to confirmed waves with a later actual confirmation', () => {
  const base = { bc: true, type: 'macd_wave', status: 'confirmed', direction: 'down',
    signal_index: 10, confirmed_index: 13, curr_date: '2026-09-11', confirmed_date: '2026-09-16' }
  for (const direction of ['up', 'down']) {
    const event = { ...base, direction }
    assert.deepEqual(macdPrompts([event]), [event])
  }
  for (const change of [{ type: 'qs' }, { type: 'macd' }, { type: 'macd_wave_special' }, { type: 'macd_wave_nonstandard' }, { status: 'candidate' },
    { status: 'superseded' }, { bc: false }, { confirmed_index: 10 },
    { confirmed_index: null }, { signal_index: -1 }, { direction: undefined },
    { confirmed_date: null }]) {
    assert.deepEqual(macdPrompts([{ ...base, ...change }]), [])
  }
})

test('four families retain independent records and nonstandard uses a triangle', () => {
  const base = { bc: true, direction: 'down', status: 'candidate', signal_index: 15, evidence: {} }
  const standard = {...base, type: 'macd_wave'}
  const nonstandard = {...base, type: 'macd_wave_nonstandard'}
  const special = {...base, type: 'macd_wave_special'}
  const local = {...base, type: 'macd', evidence: {special_no_c: 1}}
  const source = [local, standard, nonstandard, special]
  assert.deepEqual(visibleDivergences(source), source)
  assert.equal(source.length, 4) // original evidence record is not deleted
  assert.equal(divergenceMarker(standard).itemStyle.borderColor, '#cf8ff5')
  assert.equal(divergenceMarker(nonstandard).itemStyle.borderColor, '#cf8ff5')
  assert.equal(divergenceMarker(nonstandard).symbol, 'triangle')
  assert.equal(divergenceMarker(special).symbolSize, 13)
  assert.equal(divergenceMarker(special).itemStyle.color, 'transparent')
  assert.equal(divergenceMarker({...special, status:'confirmed'}).itemStyle.color, 'transparent')
  const confirmed = {...special, status:'confirmed', confirmed_index:20,
    evidence:{reverse_pen_start:15, reverse_pen_end:18, reverse_pen_confirmed:20}}
  assert.equal(divergenceMarker(confirmed).itemStyle.color, '#cf8ff5')
  assert.deepEqual(visibleDivergences([local, {...special, status:'superseded'}]), [local])
  assert.deepEqual(visibleDivergences([local, {...special, direction:'up'}]), [local, {...special, direction:'up'}])
  assert.match(divergenceName(nonstandard), /非标准波段底背离/)
  assert.match(divergenceEvidence(nonstandard).join('\n'), /只取消 DEA 极值改善，仍检查 B\/C 的 DEA 零轴及 B 双线回拉/)
  assert.match(divergenceEvidence(standard).join('\n'), /B 最低 > A 最低、C 最低 ≤ A 最低/)
  assert.match(divergenceEvidence(special).join('\n'), /前一 A 色柱段/)
  assert.match(divergenceEvidence(special).join('\n'), /不计算 C 面积/)
})

test('October 4 marker matrix uses shape for family and colour only for direction', () => {
  for (const direction of ['up','down']) for (const [type,symbol,size] of [
    ['macd','circle',9],['macd_wave','diamond',9],
    ['macd_wave_nonstandard','triangle',9],['macd_wave_special','diamond',13]]) {
    const base = {bc:true,type,direction,signal_index:10,status:'candidate',evidence:{rule_version:20261004}}
    const pending = divergenceMarker(base)
    assert.equal(pending.symbol,symbol)
    assert.equal(pending.symbolSize,size)
    assert.equal(pending.itemStyle.borderColor,direction==='up'?'#61dfa0':'#cf8ff5')
    assert.equal(pending.itemStyle.color,'transparent')
    const solid=divergenceMarker({...base,status:'confirmed',confirmed_index:14,
      evidence:{rule_version:20261004,reverse_pen_start:10,reverse_pen_end:13,reverse_pen_confirmed:14}})
    assert.equal(solid.itemStyle.color,pending.itemStyle.borderColor)
  }
})

test('special AB evidence separates A line extrema from both price anchors and legacy pivots', () => {
  const item = {type:'macd_wave_special', direction:'down', evidence: {
    special_a_segment_extrema:1, previous_dif:-4, dif:-1.5, previous_dea:-3.5, dea:-1.2,
    previous_price:10, price:9}, intervals: {a_dif_extreme_index:'2026-01-04', a_dea_extreme_index:'2026-01-06'}}
  const text = divergenceEvidence(item).join('\n')
  for (const phrase of ['A 段内各自的最低值', 'DIF · A 段极值 → B 极值当根：-4.00 → -1.50',
    'DEA · A 段极值 → B 极值当根：-3.50 → -1.20', 'A 段 DIF 极值时间：2026-01-04',
    'A 段 DEA 极值时间：2026-01-06', '原最近局部极值双线记录仍保留']) assert.ok(text.includes(phrase))
  assert.match(divergenceEvidence({...item, evidence:{}}).join('\n'), /旧版记录/)
})

test('history is opt-in, inactive stays grey hollow, never creates M1', () => {
  const old={bc:true,type:'macd_wave_nonstandard',status:'superseded',direction:'down',
    detected_index:10, invalidated_index:15, invalidated_date:'2026-09-15',evidence:{rule_version:2026100414}}
  assert.deepEqual(visibleDivergences([old]),[])
  assert.deepEqual(visibleDivergences([old],true),[old])
  assert.equal(divergenceMarker(old),null)
  const mark=divergenceMarker(old,true)
  assert.equal(mark.itemStyle.color,'transparent')
  assert.equal(mark.itemStyle.borderColor,'#8e949e')
  assert.equal(mark.itemStyle.opacity,.5)
  assert.deepEqual(macdPrompts([old]),[])
  assert.match(divergenceEvidence(old).join('\n'),/没有可关联的同类替代候选/)
})

test('new nonstandard evidence relaxes prices only and records each subtype', () => {
  for (const reaches of [0,1]) {
    const base={bc:true,type:'macd_wave_nonstandard',status:'candidate',direction:'down',
      evidence:{rule_version:2026100414,c_price_reaches_a:reaches}}
    const evidence=divergenceEvidence(base).join('\n')
    assert.match(evidence,/B 最低 ≥ A 最低/)
    assert.match(evidence,/C 与 A 不限制价格高低/)
    assert.ok(evidence.includes(reaches?'价格达到前极值':'价格未达到前极值 · 动能减弱'))
    assert.equal(divergenceMarker({...base,preliminary_index:10}).itemStyle.color,'transparent')
    assert.deepEqual(macdPrompts([{...base,status:'confirmed'}]),[])
  }
})

test('new dual rule cannot fill without recorded later local confirmation', () => {
  const value={bc:true,type:'macd',status:'confirmed',signal_index:10,confirmed_index:18,
    evidence:{rule_version:2026100414}}
  assert.equal(divergenceMarker(value).itemStyle.color,'transparent')
})
