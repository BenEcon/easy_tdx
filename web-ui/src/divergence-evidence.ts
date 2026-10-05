import type { ChanlunDivergence, ChanlunSignal, WaveCheck, WaveComparison, WaveDiagnostic } from './types'
import { isSpecialDualLine } from './divergence-marker.ts'

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
  if (item.type === 'macd_wave_special') return `特殊波段${side}背离`
  if (item.type === 'macd_wave_nonstandard') return `非标准波段${side}背离`
  if (item.type === 'macd_wave') return `标准波段${side}背离`
  if (item.type === 'macd') return `双线${side}背离`
  if (item.type === 'pz') return `盘整力度${side}背驰`
  return `趋势${side}背驰`
}

export function divergenceEvidence(item: ChanlunDivergence): string[] {
  const e = item.evidence ?? {}
  const dates = item.intervals ?? {}
  const lines: string[] = []
  if (e.rule_version) lines.push(`规则版本：${e.rule_version} · 自定义 MACD 背离；不改变缠论结构递归。`)
  if (e.reverse_pen_local === 1) lines.push('局部反向笔确认：沿用当时完整行情的包含处理、严格分型高低价与独立 K 线间距；不要求被全局笔序列选中，不改变结构笔。')
  if (item.type === 'macd_wave_special') {
    lines.push('特殊波段独立对照前一 A 色柱段：底在红柱 B 内达到或跌破 A 低点，顶在绿柱 B 内达到或突破 A 高点；不跳用其它更早的 A。')
    lines.push(e.special_a_segment_extrema === 1
      ? 'B 新价格极值当根的 DIF、DEA，分别比较前一完整 A 段内各自的最低值（底）／最高值（顶）：底双线抬高、顶双线降低，比较值均须同在对应零轴侧。A 的两个指标极值可不在同一根 K 线上，不取 A 价格极值当根，也不取 B 段内指标极值。'
      : '旧版记录：DIF、DEA 比较 A 与 B 价格极值各自当根；并非当前的 A 段内指标极值口径，请重新分析。')
    lines.push('不要求 C 色柱存在，不计算 C 面积或面积比；反向笔首次满足严格价格、分型和间距即确认，无需下一笔锁定。不生成 M1。原最近局部极值双线记录仍保留，分别查看依据。')
    if (dates.reverse_pen_start) lines.push(`反向笔：${dates.reverse_pen_start} — ${dates.reverse_pen_end}；完成可知：${dates.reverse_pen_confirmed}`)
  }
  if (item.type === 'macd') {
    if (isSpecialDualLine(item)) {
      lines.push(`柱色备注：极值当时为${item.direction === 'up' ? '绿' : '红'}柱；仍显示双线圆形，不冒用特殊波段大菱形。`)
      lines.push('仍按原双线依据判定：空心等待从该极值起的反向成笔，确认后才实心；不将缺失的 C 当作零面积，不作为标准波段背离或 M1。')
    }
    lines.push('参照：最近局部高／低点，不跳过中间极值；候选不要求成笔，最终确认须从信号极值起首次形成满足严格价格、分型和间距的反向笔，无需下一笔锁定。')
    if (dates.reverse_pen_start) lines.push(`反向笔：${dates.reverse_pen_start} — ${dates.reverse_pen_end}；完成可知：${dates.reverse_pen_confirmed}`)
  }
  if (item.type === 'macd_wave' || item.type === 'macd_wave_nonstandard') {
    const nonstandard = item.type === 'macd_wave_nonstandard'
    lines.push(nonstandard
      ? '非标准独立比较完整同色 A 与 C：面积、价格和 DIF 极值均取完整 A，A 可跨轴；完整 B、C 的 DIF、DEA 须始终在目标零轴侧，不截取 B、C。'
      : '波段独立比较 A、C，不要求最近局部极值双线背离。A 从双线最后一次进入目标零轴一侧后重新起算；有效 ABC 全程双线同侧，B、C 不截取跨轴部分。')
    lines.push(nonstandard && e.rule_version === 2026100414
      ? '价格条件：底背离 B 最低 ≥ A 最低；顶背离 B 最高 ≤ A 最高；C 与 A 不限制价格高低。'
      : '价格条件：底背离 B 最低 > A 最低、C 最低 ≤ A 最低；顶背离 B 最高 < A 最高、C 最高 ≥ A 最高。')
    if (nonstandard && e.c_price_reaches_a !== undefined) lines.push(e.c_price_reaches_a
      ? '价格关系：价格达到前极值。' : '价格关系：价格未达到前极值 · 动能减弱；确认不代表底部或顶部已确定。')
    lines.push('连续两根同色柱缩短仅作初步确认；C 段柱色反转后，整段复核通过才最终确认。')
    lines.push(nonstandard
      ? '非标准：C 同色柱面积小于完整 A，C 段 DIF 最低值抬高（底）／最高值降低（顶）；只取消 DEA 极值改善，仍检查 B/C 的 DEA 零轴及 B 双线回拉，不使用 DEA 容差。不生成 M1。'
      : '力度须同时满足 C 同色柱面积小于 A，以及 C 段 DIF、DEA 各自最低值抬高（底）／最高值降低（顶）。取各自整个比较段，不只取股价极值当天；两条线须同时改善。')
    if (e.a_axis_trimmed) lines.push(`A 段重新起算：原色柱段 ${dates.original_a_start ?? '—'} — ${dates.original_a_end ?? '—'}；有效起点 ${dates.a_start ?? '—'}。价格、面积和参与判定的线极值均仅取有效段。`)
    else if (dates.original_a_start) lines.push(`原始 A 与比较 A 相同：${dates.original_a_start} — ${dates.original_a_end}；${nonstandard ? '完整 A 可跨轴，不截取' : '双线全程符合轴侧，无需截取'}。`)
    lines.push('B 回拉单独检查：只取 B 内 DIF、DEA 向零轴靠近的值，不借用 A 末根或 C 首根。')
    for (const line of ['dif', 'dea']) if (dates[`c_${line}_extreme_index`]) {
      lines.push(`${line.toUpperCase()} 段内极值时间：A ${dates[`a_${line}_extreme_index`]} / C ${dates[`c_${line}_extreme_index`]}`)
    }
  }
  if (e.reverse_pen_first_formed === 1) lines.push(`首次成笔确认：${dates.reverse_pen_formed_index ?? item.confirmed_date}；独立 K 线间距 ${e.reverse_pen_gap}；端点 ${pairValues(e.reverse_pen_start_price!, e.reverse_pen_end_price!)}。已保存当时证据，后续结构锁定不改变此确认时间。`)
  if (e.reverse_pen_waiting === 1 && item.status === 'candidate') {
    const reason = ({1: '本次极值尚未成为有效分型', 2: '尚无后续反向分型',
      3: '反向顶底分型未通过严格高低价条件',
      4: `独立合并 K 线间距不足（${e.reverse_pen_observed_gap} / 要求 ${e.reverse_pen_required_gap}）`,
      5: '该端点组合未被当前严格笔链接受'} as Record<number, string>)[e.reverse_pen_wait_code ?? 0]
    lines.push(`确认尚未通过：截至 ${dates.reverse_pen_checked_index ?? '当前快照'}，${reason ?? '尚未形成从本次极值起的有效反向笔'}。`)
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
      const segmentReference = item.type === 'macd_wave_special' && e.special_a_segment_extrema === 1
        && (label === 'DIF' || label === 'DEA')
      lines.push(`${segmentReference ? `${label} · A 段极值 → B 极值当根` : label}：${pairValues(e[before!]!, e[after!]!)}`)
      if (segmentReference) lines.push(`A 段 ${label} 极值时间：${dates[`a_${label!.toLowerCase()}_extreme_index`] ?? '—'}`)
    }
  }
  if (Number.isFinite(e.area_ratio)) lines.push(`面积比 C/A：${(e.area_ratio! * 100).toFixed(2)}%`)
  if (item.preliminary_date) lines.push(`初步确认：${item.preliminary_date}；非最终确认，仍须${item.type === 'macd' || item.type === 'macd_wave_special' ? '已确认反向笔' : 'C 段完成及整段复核'}。`)
  if (item.invalidated_date) lines.push(`失效／替代：${item.invalidated_date}；${item.failure_reason || '条件不再成立'}`)
  if (dates.replacement_signal_index) lines.push(`后续替代候选极值：${dates.replacement_signal_index}；首次提示：${dates.replacement_detected_index}（同类独立记录，不等于已确认）。`)
  else if (item.status === 'superseded') lines.push('失效当时没有可关联的同类替代候选；新价格极值本身不等于新信号。')
  if (item.failure_audit?.checks?.length) {
    lines.push(`失效当时复核（${item.failure_audit.dates.known_index ?? item.invalidated_date ?? '—'}）：上方为候选最后通过时的依据，下方为首次失效时的数值，不用后续走势覆盖。`)
    lines.push(...item.failure_audit.checks.filter(check => !check.passed).map(waveCheckLine))
  }
  lines.push(`价格极值日：${item.curr_date ?? '—'}`)
  lines.push(`首次提示：${item.detected_date ?? '—'}；确认：${item.confirmed_date ?? '尚未确认'}`)
  return lines
}

const waveGates: Record<string, string> = {
  dual_reference_available: '已有反向波动隔开的最近局部参照极值',
  special_complete_a: '特殊对照的 A 起点未被行情窗口截断',
  dual_price_break: '严格突破最近局部价格极值',
  dual_dif_improves: '两价格极值当根 DIF 改善且同侧',
  dual_dea_improves: '两价格极值当根 DEA 改善且同侧',
  reverse_pen_formed: '从候选极值起的反向笔首次成立',
  candidate_price_retained: '候选未被后续新价格极值替代',
  candidate_dif_retained: '后续 DIF 仍优于冻结参照',
  candidate_dea_retained: '后续 DEA 仍优于冻结参照',
  a_full_colour_run: '完整同色 A 可比较（不截取跨轴部分）',
  special_ab_finite: 'A、B 数据完整',
  special_b_price_break: 'B 达到或突破前一 A 的价格极值',
  special_dif_price_extreme: '两个价格极值当根 DIF 改善且同侧',
  special_dea_price_extreme: '两个价格极值当根 DEA 改善且同侧',
  special_dif_a_segment_extreme: 'B 价格极值当根 DIF 优于 A 段内 DIF 极值且同侧',
  special_dea_a_segment_extreme: 'B 价格极值当根 DEA 优于 A 段内 DEA 极值且同侧',
  special_candidate_retained: '特殊候选未被后续价格／双线失效条件替代',
  b_price_inside_a: 'B 不触及或突破 A 的价格极值（底更高、顶更低）',
  b_price_not_beyond_a: 'B 不突破 A 的价格极值（允许相等）',
  c_price_unrestricted: '非标准 C 与 A 不限制价格高低（保留面积与 DIF 检查）',
  complete_colour_abc: '完整色柱三段（A 起点不能被行情窗口截断）',
  original_abc_finite: '原 ABC 行情和指标数值完整',
  a_axis_suffix: 'A 存在双线进入目标零轴一侧后的连续尾段',
  dea_zero_axis_without_improvement: 'DEA 段内极值位于目标零轴一侧，不要求改善',
  ordered_complete_intervals: 'A、C 区间完整且先后有序',
  dif_finite_coverage: 'DIF 数值完整', dea_finite_coverage: 'DEA 数值完整', hist_finite_coverage: '柱值完整',
  strict_price_extreme: 'C 严格突破有效 A 的价格极值',
  equal_or_new_price_extreme: 'C 达到或突破 A 的价格极值（仅 0.000001 数值容差）',
  shrinking_same_colour_area: 'C 同色柱面积小于比较 A',
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
    special_ab_finite: 'A、B 行情或指标不完整',
    special_b_price_break: 'B 尚未达到前一 A 的价格极值',
    special_dif_price_extreme: '价格极值当根 DIF 未改善或轴侧不符',
    special_dea_price_extreme: '价格极值当根 DEA 未改善或轴侧不符',
    special_dif_a_segment_extreme: 'B 价格极值当根 DIF 未优于 A 段 DIF 极值或轴侧不符',
    special_dea_a_segment_extreme: 'B 价格极值当根 DEA 未优于 A 段 DEA 极值或轴侧不符',
    special_candidate_retained: '后续新极值或双线变化使候选失效',
    b_price_inside_a: 'B 最低未高于 A 最低，或 B 最高未低于 A 最高',
    b_price_not_beyond_a: 'B 最低低于 A 最低，或 B 最高高于 A 最高',
    complete_colour_abc: '缺少完整三段，或原 A 起点被窗口截断',
    original_abc_finite: '原 ABC 存在缺失或无效指标值',
    a_axis_suffix: 'A 尚无双线同在目标零轴一侧的有效尾段',
    dea_zero_axis_without_improvement: 'DEA 极值不在目标零轴一侧',
    strict_price_extreme: 'C 未突破有效 A 的价格极值',
    equal_or_new_price_extreme: 'C 仍未达到 A 的价格极值',
    shrinking_same_colour_area: 'C 同色柱面积未小于比较 A',
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
  if (check.gate === 'b_price_inside_a' && typeof v.a_price === 'number' && typeof v.b_price === 'number') {
    detail += `；价格 A → B ${pairValues(v.a_price, v.b_price)}；要求 B ${v.direction === 'down' ? '最低 > A 最低' : '最高 < A 最高'}`
  }
  if (check.gate === 'special_b_price_break' && typeof v.a_price === 'number' && typeof v.b_price === 'number') {
    detail += `；价格 A → B ${pairValues(v.a_price, v.b_price)}`
  }
  if (check.gate.startsWith('special_') && typeof v.previous_value === 'number' && typeof v.current_value === 'number') {
    detail += `；${check.gate.endsWith('_a_segment_extreme') ? 'A 段指标极值 → B 价格极值当根' : '价格极值当根 A → B'} ${pairValues(v.previous_value, v.current_value)}`
  }
  if (check.gate.startsWith('special_') && check.dates?.previous_index) {
    detail += `；${check.gate.endsWith('_a_segment_extreme') ? 'A 指标极值' : 'A 价格极值'} ${check.dates.previous_index} / B 价格极值 ${check.dates.current_index}`
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
  const lines = [`核验截至 ${d.known_index ?? '—'}；${item.family === 'double' ? '最近局部价格极值双线对照；确认须反向笔首次成立' : item.family === 'special' ? '特殊 AB 观察，C 可有可无；确认须反向笔首次成立' : item.closed ? 'C 色柱段已结束' : 'C 色柱段进行中'}。`]
  if (item.family === 'nonstandard') lines.push('完整 A 可跨轴，价格、面积和 DIF 极值均取完整 A；保留 B/C 双线同侧及 B 内回拉，只取消 DEA 极值改善。')
  if (d.original_a_start) lines.push(`原 A：${d.original_a_start} — ${d.original_a_end}`)
  if (d.a_start) lines.push(`${item.family === 'double' ? '参照局部极值' : '比较 A'}：${d.a_start} — ${d.a_end}`)
  if (d.b_start) lines.push(`B：${d.b_start} — ${d.b_end}`)
  if (item.family !== 'special') lines.push(`${item.family === 'double' ? '当前局部极值' : 'C'}：${d.c_start ?? '—'} — ${d.c_end ?? '—'}`)
  lines.push(...item.checks.map(waveCheckLine))
  for (const r of item.rejections) lines.push(`拦截记录 ${r.from_date} — ${r.through_date}：${r.gates.map(g => waveGates[g] ?? '未识别的检查条件').join('；')}`)
  return lines
}
