import {factorValue} from './factor-research.ts'

/** Tick presentation only. Tooltip, table, stored data and exports keep raw units. */
export function factorAxisValue(value:number,percent=false):string {
  if(!Number.isFinite(value))return '—'
  const displayed=percent?value*100:value
  if(!Number.isFinite(displayed))return '—'
  const magnitude=Math.abs(displayed),suffix=percent?'%':''
  if(magnitude>=10000){
    const [scale,unit]=magnitude>=1e12?[1e12,'万亿'] as const:magnitude>=1e8?[1e8,'亿'] as const:[1e4,'万'] as const
    // Keep enough precision for narrowly spaced large ticks, not just 2 decimals.
    return `${Number((displayed/scale).toPrecision(12))}${unit}${suffix}`
  }
  if(magnitude!==0&&magnitude<0.1){
    return `${magnitude<1e-4?displayed.toExponential(2).replace(/\.?0+(?=e)/,''):Number(displayed.toPrecision(6))}${suffix}`
  }
  return factorValue(value,percent)
}
