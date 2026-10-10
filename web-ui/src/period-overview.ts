import { studyStatus, type StudyRow, type StudyPeriod } from './research-study.ts'

/** User-requested default matrix, ordered from larger to smaller periods. */
export const overviewPeriods: StudyPeriod[] = ['WEEK', 'DAY', 'MIN_30', 'MIN_15', 'MIN_5']
export const overviewColumns = ['均线 / 价格', '成交量', 'MACD', '严格笔与当前方向', '背离', '买卖点', '其他'] as const
const number = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '不可计算'
const direction = (value: string) => value === 'up' ? '向上' : value === 'down' ? '向下' : '方向未记录'
const families: Record<string, string> = { macd_wave: '标准波段', macd_wave_nonstandard: '非标准波段', macd_wave_special: '特殊波段', macd: '双线', pz: '盘整力度', qs: '趋势', bi: '笔力度' }
const pointNames: Record<string,string> = {'1buy':'一买','2buy':'二买','3buy':'三买','1sell':'一卖','2sell':'二卖','3sell':'三卖'}
export function buySellOverview(row: StudyRow): string[] {
  if (!row.buy_sell_points) return ['此历史结果未记录买卖点，需重新分析；不能视为没有买卖点']
  if (!row.buy_sell_points.length) return ['研究窗口内无已确认买卖点或 M1 提示；不代表历史从未出现']
  return row.buy_sell_points.map(point => `${point.family === 'macd' ? `M1 · MACD ${point.side === 'buy' ? '买入' : '卖出'}提示（非结构一类点）` : `结构${pointNames[point.type] ?? point.type}`} · ${studyStatus(point.status)}；极值 ${point.date} · ${number(point.price)}；确认 ${point.known_at ?? point.confirmed_date}；${point.reason}`)
}

/** Presentation only. All states, periods and causal evidence remain server-owned. */
export function periodOverviewCells(row: StudyRow): string[][] {
  const pen = row.direction_observation.strict
  const divergence = row.divergences.slice().sort((a, b) => b.date.localeCompare(a.date)).map(item => {
    const name = `${families[item.kind ?? ''] ?? '类型未记录'}${item.direction === 'up' ? '顶' : item.direction === 'down' ? '底' : ''}${['pz', 'qs', 'bi'].includes(item.kind ?? '') ? '背驰' : '背离'}`
    return `${name} · ${studyStatus(item.status)}；极值 ${item.date}${item.confirmed_date ? `；确认 ${item.confirmed_date}` : ''}`
  })
  return [
    [`收盘 ${number(row.price)}`, `MA5 ${number(row.pairs.ma.fast)} / MA10 ${number(row.pairs.ma.slow)}`,
      row.pairs.ma.description,
      `多头${row.ma_research.bull.to ? `至 MA${row.ma_research.bull.to}` : '未排列'} · 空头${row.ma_research.bear.to ? `至 MA${row.ma_research.bear.to}` : '未排列'}`],
    [`MAVOL5 ${number(row.pairs.volume.fast)}`, `MAVOL10 ${number(row.pairs.volume.slow)}`,
      row.pairs.volume.description, `本根 / 前 20 根均量：${number(row.volume_ratio)}${row.volume_ratio != null && Number.isFinite(row.volume_ratio) ? ' 倍' : ''}`],
    [`DIF ${number(row.pairs.macd.fast)} / DEA ${number(row.pairs.macd.slow)}`,
      `${row.axis} · ${row.histogram}`, row.pairs.macd.description],
    [pen ? `${direction(pen.direction)}严格笔 · ${pen.locked ? '已被反向笔锁定' : '末端可延伸'}` : '尚无严格笔',
      ...(pen ? [`${pen.start_date} → ${pen.end_date}；${number(pen.start_price)} → ${number(pen.end_price)}`] : []),
      `当前观察：${row.direction_observation.description}`,
      ...(row.direction_observation.known_date ? [`观察可知：${row.direction_observation.known_date}`] : [])],
    divergence.length ? divergence : ['本研究窗口未返回有效背离记录；不代表历史从未出现'],
    buySellOverview(row),
    [...row.observations, ...(row.warmup_warning ? ['EMA 预热不足 120 根'] : []),
      ...(row.window.truncated ? ['所请求研究窗口覆盖不足'] : []),
      ...(row.excluded_bars ? [`排除 ${row.excluded_bars} 根未收盘或截止后行情`] : []),
      `观察窗口：${row.window.start} — ${row.window.end}（${row.window.count} 根）`],
  ]
}
