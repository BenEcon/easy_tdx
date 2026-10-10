import type { BarSnapshot } from './api'
import type { Category } from './types'

export const comparisonPeriods: ReadonlyArray<{ value: Category; label: string }> = [
  { value: 'MONTH', label: '月线' }, { value: 'WEEK', label: '周线' },
  { value: 'DAY', label: '日线' }, { value: 'MIN_60', label: '60 分钟' },
  { value: 'MIN_30', label: '30 分钟' }, { value: 'MIN_15', label: '15 分钟' },
  { value: 'MIN_5', label: '5 分钟' }, { value: 'MIN_1', label: '1 分钟' },
]
export const periodLabel = (value: Category) => comparisonPeriods.find(item => item.value === value)!.label

// Compare exchange-local timestamps without applying the browser's timezone.
function localStamp(value: string | undefined): string {
  const stamp = value?.replace('T', ' ')
  if (!stamp || !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(stamp)) {
    throw new Error('行情缺少明确的交易所时间，暂不能进行跨周期对比')
  }
  return stamp.slice(0, 19)
}

export function alignPeriodSnapshots(primary: BarSnapshot, other: BarSnapshot, asOf: string, adjust: string) {
  for (const snapshot of [primary, other]) {
    if (snapshot.metadata?.actual_adjust !== adjust) throw new Error('两个周期的实际复权方式不一致，未生成对比')
  }
  const cutoff = [localStamp(asOf), localStamp(primary.metadata.observed_at), localStamp(other.metadata.observed_at)].sort()[0]!
  const aligned = [primary, other].map(snapshot => {
    let previous = ''
    const bars = snapshot.bars.filter(bar => {
      const stamp = localStamp(bar.datetime)
      const end = localStamp(bar.period_end)
      if (stamp <= previous || end < stamp) throw new Error('行情时间顺序或周期结束时间异常，未生成对比')
      if (typeof bar.is_closed !== 'boolean') throw new Error('行情缺少收盘标识，未生成对比')
      previous = stamp
      return bar.is_closed && end <= cutoff
    })
    return { bars, excluded: snapshot.bars.length - bars.length }
  })
  return { cutoff, primary: aligned[0]!, other: aligned[1]! }
}
