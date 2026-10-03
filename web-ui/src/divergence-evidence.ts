import type { ChanlunDivergence, ChanlunSignal, WaveCheck, WaveComparison, WaveDiagnostic } from './types'

export function signalEvidence(signal: ChanlunSignal): string[] {
  const e = signal.evidence ?? {}
  const lines = ['规则：已确认线段构成的基础结构；不是按图表周期推定的高级别结构。']
  for (const [key, title] of [['first_segment', '前置一类点线段'], ['rebound_segment', '反弹／回落线段'],
    ['departure_segment', '离开线段'], ['return_segment', '回试线段'], ['a_segment', 'A 段'], ['c_segment', 'C 段']]) {
    const value = e[key!]
    if (typeof value === 'number') lines.push(`${title}：${value + 1}`)
  }
  if (typeof e.centre_segment_count === 'number') lines.push(`中枢构成：${e.centre_segment_count} 条线段`)
  if (typeof e.zd === 'number' && typeof e.zg === 'number') lines.push(`固定核心：${e.zd.toFixed(2)} — ${e.zg.toFixed(2)}`)
  if (typeof e.area_ratio === 'number') lines.push(`MACD 柱面积 C/A：${(e.area_ratio * 100).toFixed(2)}%`)
  if (e.first_return) lines.push('首次回试已完成，未重新进入中枢。')
  if (e.strength === 'weak_new_extreme') lines.push('弱二类：回试突破首个极值；策略默认过滤。')
  lines.push(`极值位置：${signal.date ?? '—'}；可用时间：${signal.confirmed_date ?? '未确认'}`)
  return lines
}

export function divergenceName(item: ChanlunDivergence): string {
  const side = item.direction === 'up' ? '顶' : '底'
  if (item.type === 'macd_wave') return `波段${side}背离`
  if (item.type === 'macd') return `双线${side}背离`
  if (item.type === 'pz') return `盘整力度${side}背驰`
  return `趋势${side}背驰`
}

export function divergenceEvidence(item: ChanlunDivergence): string[] {
  const e = item.evidence ?? {}
  const dates = item.intervals ?? {}
  const lines: string[] = []
  if (item.type === 'macd') {
    lines.push('参照：最近局部高／低点，不跳过中间极值；提示不要求成笔，最终确认须从信号极值起形成已确认反向笔，暂定尾笔不计。')
    if (dates.reverse_pen_start) lines.push(`反向笔：${dates.reverse_pen_start} — ${dates.reverse_pen_end}；完成可知：${dates.reverse_pen_confirmed}`)
  }
  if (item.type === 'macd_wave') {
    lines.push('波段独立比较 A、C，不要求最近局部极值双线背离。A 可从双线最后一次进入目标零轴一侧后重新起算；从有效 A 到 C 结束须全程同侧，B、C 不截取跨轴部分。')
    lines.push('连续两根同色柱缩短仅作初步确认；C 段柱色反转后，整段复核通过才最终确认。')
    lines.push('力度须同时满足 C 同色柱面积小于 A，以及 C 段 DIF、DEA 各自最低值抬高（底）／最高值降低（顶）。取各自整个比较段，不只取股价极值当天；两条线须同时改善。')
    if (e.a_axis_trimmed) lines.push(`A 段重新起算：原色柱段 ${dates.original_a_start ?? '—'} — ${dates.original_a_end ?? '—'}；有效起点 ${dates.a_start ?? '—'}。价格、面积和双线极值均仅取有效段。`)
  }
  for (const segment of ['a', 'b', 'c']) {
    if (dates[`${segment}_start`]) lines.push(`${segment.toUpperCase()} 段：${dates[`${segment}_start`]} — ${dates[`${segment}_end`]}`)
  }
  const pairs = [['价格极值', 'previous_price', 'price'], ['DIF', 'previous_dif', 'dif'],
    ['DEA', 'previous_dea', 'dea'], ['柱面积 A → C', 'a_area', 'c_area'],
    ['段内 DIF 极值 A → C', 'a_dif_extreme', 'c_dif_extreme'],
    ['段内 DEA 极值 A → C', 'a_dea_extreme', 'c_dea_extreme']]
  for (const [label, before, after] of pairs) {
    if (Number.isFinite(e[before!]) && Number.isFinite(e[after!])) {
      lines.push(`${label}：${e[before!]!.toFixed(2)} → ${e[after!]!.toFixed(2)}`)
    }
  }
  if (Number.isFinite(e.area_ratio)) lines.push(`面积比 C/A：${(e.area_ratio! * 100).toFixed(2)}%`)
  if (item.preliminary_date) lines.push(`初步确认：${item.preliminary_date}；非最终确认，仍须${item.type === 'macd' ? '已确认反向笔' : 'C 段完成及整段复核'}。`)
  if (item.invalidated_date) lines.push(`失效／替代：${item.invalidated_date}；${item.failure_reason || '条件不再成立'}`)
  if (item.failure_audit?.checks?.length) {
    lines.push(`失效当时复核（${item.failure_audit.dates.known_index ?? item.invalidated_date ?? '—'}）：上方为候选最后通过时的依据，下方为首次失效时的数值，不用后续走势覆盖。`)
    lines.push(...item.failure_audit.checks.filter(check => !check.passed).map(waveCheckLine))
  }
  lines.push(`价格极值日：${item.curr_date ?? '—'}`)
  lines.push(`首次提示：${item.detected_date ?? '—'}；确认：${item.confirmed_date ?? '尚未确认'}`)
  return lines
}

const waveGates: Record<string, string> = {
  complete_colour_abc: '完整色柱三段（A 起点不能被行情窗口截断）',
  original_abc_finite: '原 ABC 行情和指标数值完整',
  a_axis_suffix: 'A 存在双线进入目标零轴一侧后的连续尾段',
  ordered_complete_intervals: 'A、C 区间完整且先后有序',
  dif_finite_coverage: 'DIF 数值完整', dea_finite_coverage: 'DEA 数值完整', hist_finite_coverage: '柱值完整',
  strict_price_extreme: 'C 严格突破有效 A 的价格极值',
  equal_or_new_price_extreme: 'C 达到或突破 A 的价格极值（仅 0.000001 数值容差）',
  shrinking_same_colour_area: 'C 同色柱面积小于有效 A',
  dif_whole_abc_zero_axis: 'DIF 在有效 ABC 全程同侧（触轴也不通过）',
  dea_whole_abc_zero_axis: 'DEA 在有效 ABC 全程同侧（触轴也不通过）',
  dif_whole_bc_zero_axis: 'DIF 在 B、C 全程同侧（只放宽 A）',
  dea_whole_bc_zero_axis: 'DEA 在 B、C 全程同侧（只放宽 A）',
  dif_whole_leg_zero_axis: 'DIF 在有效 A、C 全程同侧',
  dea_whole_leg_zero_axis: 'DEA 在有效 A、C 全程同侧',
  dif_extreme_and_zero_axis: 'DIF 段内极值改善且位于目标零轴一侧',
  dea_extreme_and_zero_axis: 'DEA 段内极值改善且位于目标零轴一侧',
  dea_extreme_tolerance: 'DEA 段内极值改善或不利偏差不超过 5%（仅研究）',
  candidate_anchor_retained: '候选价格锚点是否保留',
  dif_centre_pullback: 'B 使 DIF 向零轴回拉', dea_centre_pullback: 'B 使 DEA 向零轴回拉',
}
export function waveFailureSummary(item: { checks: WaveCheck[] }): string {
  const failed = item.checks.filter(check => !check.passed)
  const reasons: Record<string, string> = {
    complete_colour_abc: '缺少完整三段，或原 A 起点被窗口截断',
    original_abc_finite: '原 ABC 存在缺失或无效指标值',
    a_axis_suffix: 'A 尚无双线同在目标零轴一侧的有效尾段',
    strict_price_extreme: 'C 未突破有效 A 的价格极值',
    equal_or_new_price_extreme: 'C 仍未达到 A 的价格极值',
    shrinking_same_colour_area: 'C 同色柱面积未小于有效 A',
    dif_whole_abc_zero_axis: '有效 ABC 内 DIF 触轴或跨轴',
    dea_whole_abc_zero_axis: '有效 ABC 内 DEA 触轴或跨轴',
    dif_whole_bc_zero_axis: 'B、C 内 DIF 触轴或跨轴',
    dea_whole_bc_zero_axis: 'B、C 内 DEA 触轴或跨轴',
    dif_extreme_and_zero_axis: 'DIF 段内极值未改善，或不在目标零轴一侧',
    dea_extreme_and_zero_axis: 'DEA 段内极值未改善，或不在目标零轴一侧',
    dea_extreme_tolerance: 'DEA 超出 5% 容差、轴侧不符，或接近零时未严格改善',
  }
  return failed.filter(check => !check.gate.endsWith('_whole_leg_zero_axis') ||
    !failed.some(other => other.gate === check.gate.replace('_whole_leg_', '_whole_abc_')))
    .map(check => reasons[check.gate] ?? `未满足：${waveGates[check.gate] ?? '未识别的检查条件'}`).join('；')
}

function pairValues(a: number, b: number): string {
  const normal = `${a.toFixed(2)} → ${b.toFixed(2)}`
  if (a !== b && a.toFixed(2) === b.toFixed(2)) {
    const precise = a.toFixed(6) === b.toFixed(6) ? [a.toPrecision(12), b.toPrecision(12)] : [a.toFixed(6), b.toFixed(6)]
    return `${normal}（精确值 ${precise[0]} → ${precise[1]}，计算未四舍五入）`
  }
  return normal
}
export function waveCheckLine(check: WaveCheck): string {
  const v = check.values
  let detail = ''
  for (const [a, c, label] of [['a_price', 'c_price', '价格 A → C'], ['a_area', 'c_area', '面积 A → C'],
    ['a_extreme', 'c_extreme', '双线极值 A → C'], ['a_extreme', 'pullback', 'A 极值 → 回拉'],
    ['previous_price', 'price', '候选价格 → 后续极值']]) {
    if (typeof v[a!] === 'number' && typeof v[c!] === 'number') detail += `；${label} ${pairValues(v[a!] as number, v[c!] as number)}`
  }
  if (check.dates?.first_violation_index) {
    const value = typeof v.first_violation_value === 'number' ? v.first_violation_value.toFixed(6) : '—'
    detail += `；首次触轴／异侧 ${check.dates.first_violation_index}，值 ${value}，共 ${v.violation_count} 根`
  }
  if (check.dates?.c_extreme_index) detail += `；极值位置 A ${check.dates.a_extreme_index} / C ${check.dates.c_extreme_index}`
  if (check.gate.endsWith('_extreme_and_zero_axis') && v.direction) detail += v.direction === 'down' ? '；要求 C 最低值 > A 最低值，且都在零轴下方' : '；要求 C 最高值 < A 最高值，且都在零轴上方'
  if (check.dates?.replacement_index) detail += `；后续极值 ${check.dates.replacement_index}${v.same_price ? '（同价后移）' : ''}`
  if (check.gate === 'dea_extreme_tolerance') {
    detail += `；DEA 不利偏差 ${typeof v.worsening_ratio === 'number' ? (v.worsening_ratio * 100).toFixed(4) + '%' : '不适用'}；上限 5%（原始精度判定）`
    detail += v.strict_passed ? '；DEA 本身已严格改善' : v.tolerance_enabled ? '；仅容差对照，不等于严格改善' : '；|A 极值| ≤ 0.000000001，禁用相对容差，须严格改善'
  }
  return `${check.passed ? '通过' : '未通过'} · ${waveGates[check.gate] ?? '未识别的检查条件'}${detail}`
}
export function waveComparisonName(item: WaveComparison): string {
  return ({ full_a: '仅保留完整 A', equal_price: '仅允许等高／等低', full_a_equal_price: '完整 A ＋ 等高／等低', dea_tolerance: '面积缩小 ＋ DIF 改善 ＋ DEA 容差 5%' })[item.mode]
}
export function waveComparisonLines(item: WaveComparison): string[] {
  return [`核验截至 ${item.dates.known_index ?? '—'}；${item.closed ? 'C 已结束' : 'C 尚未结束，通过也只是暂时满足'}。`,
    `比较 A：${item.dates.a_start ?? '无有效段'} — ${item.dates.a_end ?? '—'}；只作规则研究，不生成 M1 或交易信号。`,
    ...(item.mode === 'dea_tolerance' ? ['研究阈值 5%，未作有效性验证；保留有效 A、价格严格突破、完整 ABC 同侧、面积缩小、DIF 严格改善与 B 回拉。DEA 比较各自段内极值，不是价格极值当天；不利偏差除以 |A 的 DEA 极值|。'] : []),
    ...item.checks.map(waveCheckLine)]
}
export function waveDiagnosticLines(item: WaveDiagnostic): string[] {
  const d = item.dates
  const lines = [`核验截至 ${d.known_index ?? '—'}；${item.closed ? 'C 色柱段已结束' : 'C 色柱段进行中'}。`]
  if (d.original_a_start) lines.push(`原 A：${d.original_a_start} — ${d.original_a_end}`)
  if (d.a_start) lines.push(`有效 A：${d.a_start} — ${d.a_end}`)
  if (d.b_start) lines.push(`B：${d.b_start} — ${d.b_end}`)
  lines.push(`C：${d.c_start ?? '—'} — ${d.c_end ?? '—'}`)
  lines.push(...item.checks.map(waveCheckLine))
  for (const r of item.rejections) lines.push(`拦截记录 ${r.from_date} — ${r.through_date}：${r.gates.map(g => waveGates[g] ?? '未识别的检查条件').join('；')}`)
  return lines
}
