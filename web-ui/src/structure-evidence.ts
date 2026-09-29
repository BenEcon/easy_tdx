import type { ChanlunCenter, ChanlunFeature, ChanlunSegment } from './types'

export function segmentsConnected(segments: ChanlunSegment[]): boolean {
  return segments.length > 0 && segments.every((segment, index) => {
    if (segment.start_date >= segment.end_date) return false
    if (!index) return true
    const previous = segments[index - 1]!
    const start = segment.start_value ?? (segment.direction === 'up' ? segment.low : segment.high)
    const end = previous.end_value ?? (previous.direction === 'up' ? previous.high : previous.low)
    return segment.start_date === previous.end_date && segment.direction !== previous.direction
      && Number.isFinite(start) && Number.isFinite(end) && Math.abs(start - end) < 1e-8
  })
}

export function centreState(state?: string): string {
  return ({ formed: '已形成', extended: '延伸中', departed: '离开待回试', exited: '回试确认退出' } as Record<string, string>)[state ?? ''] ?? '辅助重叠区'
}

const numbers = (items: number[]) => items.map(index => index + 1).join('、')
const range = (low: number, high: number) => `${low.toFixed(2)}–${high.toFixed(2)}`
const relationLabel = (relation?: string) => ({ initial: '首个基础中枢', separated_up: '外围向上分离', separated_down: '外围向下分离', expansion_candidate: '扩展候选，尚非已确认高级别中枢', overlapping: '与前中枢重叠' } as Record<string, string>)[relation ?? '']

export function centreEvidence(centre: ChanlunCenter): string[] {
  const lines = [
    `固定核心：${range(centre.zd, centre.zg)}；外围：${range(centre.dd, centre.gg)}`,
    `形成确认时间：${centre.formed_date ?? '未提供'}`,
    `初始三段：${numbers(centre.seed_segments ?? []) || '未提供'}`,
    `组成线段：${numbers(centre.member_segments ?? []) || '未提供'}`,
  ]
  const relation = relationLabel(centre.relation_at_formation)
  if (relation) lines.push(`形成时与前中枢的关系：${relation}`)
  if (centre.relation_history?.length) {
    lines.push(`当前关系：${relationLabel(centre.relation_current) ?? '未提供'}`)
    for (const event of centre.relation_history) {
      const overlap = event.envelope_overlap ? `外围交集 ${range(...event.envelope_overlap)}` : '外围无交集'
      lines.push(`${event.known_date} · 与中枢 ${event.previous_centre + 1}：${relationLabel(event.relation) ?? '未提供'}；${overlap}；${event.both_exited ? '两中枢已确认退出' : '后中枢尚未确认退出'}`)
    }
    lines.push('关系按已纳入线段计算，待回试离开段不计入外围；退出不代表趋势结束，也不确认递归级别。')
  }
  for (const event of centre.transitions ?? []) {
    lines.push(`${event.known_date} · 线段 ${event.segment_index + 1} · ${centreState(event.state)}`)
  }
  return lines
}

function featureLines(features: ChanlunFeature[], label: string): string[] {
  return features.map((item, index) => `${label} ${index + 1}：${range(item.low, item.high)}；来源笔 ${numbers(item.pen_indices)}；高点来自笔 ${item.high_pen + 1}，低点来自笔 ${item.low_pen + 1}`)
}

export function segmentEvidence(segment: ChanlunSegment): string[] {
  const evidence = segment.evidence
  if (!evidence) return ['此结果未提供特征序列依据，请重新分析。']
  const rule = evidence.case === 'boundary_inclusion_break' ? '特殊包含（第 71、78 课）：分界两侧不合并，反向三笔及后续突破确认' : evidence.case === 'gap_reverse_fractal' ? '存在缺口，等待反向特征序列分型确认' : evidence.case === 'no_gap_fractal' ? '无缺口，特征序列分型确认' : '确认方式未提供'
  return [
    `确认方式：${rule}`,
    `极值端点：${segment.end_date}；确认时间：${segment.confirmed_date ?? '未提供'}`,
    `线段组成：笔 ${evidence.start_pen + 1}–${evidence.end_pen + 1}`,
    ...(evidence.supporting_pen == null ? [] : [`确认所需最后一笔：${evidence.supporting_pen + 1}（可位于线段端点之后）`]),
    ...featureLines(evidence.features ?? [], '特征元素'),
    ...featureLines(evidence.reverse_features ?? [], '反向确认元素'),
  ]
}
