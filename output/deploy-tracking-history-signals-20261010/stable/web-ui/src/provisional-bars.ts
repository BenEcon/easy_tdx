/** Preserve price/volume values: only the unconfirmed bar's outline changes. */
export function provisionalColumn(value: number, closed: boolean | undefined, rising: boolean) {
  return closed === false ? {
    value,
    itemStyle: { color: 'transparent', borderColor: rising ? '#ff7a85' : '#53d696', borderWidth: 1, borderType: 'dashed' },
  } : value
}

export function provisionalCandle(value: number[], closed: boolean | undefined) {
  return closed === false ? {
    value,
    itemStyle: { color: 'transparent', color0: 'transparent', borderType: 'dashed', borderWidth: 1.2 },
  } : value
}
