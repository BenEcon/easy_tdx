export function engineeringSource(id: string): string {
  const segment = /^segment:(\d+)$/.exec(id)
  if (segment) return `线段 ${Number(segment[1]) + 1}`
  const movement = /^movement:(trend|consolidation):L([1-9]\d*):(\d+):(\d+)$/.exec(id)
  if (movement && Number(movement[4]) >= Number(movement[3])) {
    return `M${movement[2]} ${movement[1] === 'trend' ? '趋势' : '盘整'}（线段 ${Number(movement[3]) + 1}–${Number(movement[4]) + 1}）`
  }
  const trend = /^trend:L([1-9]\d*):(\d+):(\d+)$/.exec(id)
  if (trend && Number(trend[3]) >= Number(trend[2])) {
    return `T${trend[1]} 趋势（线段 ${Number(trend[2]) + 1}–${Number(trend[3]) + 1}）`
  }
  return '未知来源'
}

export function engineeringValue(value?: number): string {
  return value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(2)
}

export function recursiveRelation(relation: string): string {
  return ({ initial: '本连续链首个中枢', separated_up: '外围向上分离', separated_down: '外围向下分离',
    expansion_candidate: '外围相交，扩展待判定', overlapping: '与前中枢重叠' } as Record<string, string>)[relation] ?? '关系未提供'
}

export function admissionReason(reason: string): string {
  return ({ seed_formation: '初始三单元形成', failed_departure_return: '回试失败后纳入',
    extension: '中枢延伸接纳' } as Record<string, string>)[reason] ?? '接纳方式未提供'
}
