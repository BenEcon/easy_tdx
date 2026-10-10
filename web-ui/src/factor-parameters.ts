export type FactorParameters = Record<string, Record<string, number>>
export type FactorDefinition = Record<string, unknown>
type Parameter = {default:number;value?:number;editable:boolean;min?:number;max?:number;unit?:string;step?:number;integer?:boolean;label?:string}

// Server publishes declarative dependency paths, never executable expressions.
function compoundWarmup(definition:FactorDefinition, values:Record<string,number>):number|undefined {
  const terms=definition.warmup_terms
  if(!Array.isArray(terms)||!terms.length)return undefined
  const specs=definition.parameters as Record<string,Parameter>|undefined
  const paths=terms.map(term=>{
    if(!term||!Number.isInteger(term.offset)||!Array.isArray(term.windows))return NaN
    return term.windows.reduce((sum:number,key:unknown)=>typeof key==='string'&&specs?.[key]?sum+(values[key]??specs[key].default):NaN,term.offset)
  })
  return paths.every(Number.isFinite)?Math.max(...paths):undefined
}

export function editableFactorParameters(definition:FactorDefinition) {
  return Object.entries((definition.parameters ?? {}) as Record<string,Parameter>).filter(([,p])=>p.editable===true)
}

export function selectedFactorParameters(names:readonly string[], values:FactorParameters):FactorParameters {
  return Object.fromEntries(names.filter(name=>Object.keys(values[name]??{}).length).map(name=>[name,{...values[name]}]))
}

export function resetFactorParameter(values:FactorParameters,name:string,key:string):FactorParameters {
  const next={...values,[name]:{...values[name]}}
  delete next[name]![key]
  if(!Object.keys(next[name]!).length)delete next[name]
  return next
}

export function parameterizedFactorName(definition:FactorDefinition, parameters:Record<string,number>={}) {
  const title=String(definition.display_name??definition.description??definition.name??'')
  const window=parameters.window
  if(definition.library==='qlib_alpha158'&&window!==undefined)return title.replace(/ · \d+周期$/,` · ${window}周期`)
  const specs=Object.fromEntries(editableFactorParameters(definition))
  if(definition.parameterized_title&&Object.entries(parameters).some(([key,value])=>value!==specs[key]?.default)){
    const values=Object.fromEntries(Object.entries(specs).map(([key,spec])=>[key,parameters[key]??spec.default]))
    const suffix=Object.keys(values).length===1&&values.window!==undefined?`${values.window}周期`:Object.entries(values).map(([key,value])=>`${specs[key]?.label??key} ${value}`).join(' / ')
    return `${definition.parameterized_title} · ${suffix}`
  }
  return title
}

export function factorParameterError(names:readonly string[], definitions:FactorDefinition[], values:FactorParameters):string {
  const identities=new Set<string>()
  for(const name of names){
    const definition=definitions.find(d=>d.name===name)
    if(!definition)continue
    const specs=Object.fromEntries(editableFactorParameters(definition))
    for(const [key,value] of Object.entries(values[name]??{})){
      const spec=specs[key]
      if(!spec||!Number.isFinite(value)||(spec.integer!==false&&!Number.isInteger(value))||value<(spec.min??2)||value>(spec.max??600))return `${name}：${spec?.label??'窗口'}须为 ${spec?.min??2}—${spec?.max??600} 的${spec?.integer===false?'数值':'整数'}`
    }
    const defaults=definition.parameters as Record<string,Parameter>|undefined
    const effective=Object.fromEntries(Object.entries(defaults??{}).map(([key,p])=>[key,values[name]?.[key]??p.default]))
    if(effective.short!==undefined&&effective.long!==undefined&&effective.short>=effective.long)return `${name}：短窗口必须小于长窗口。`
    const warmup=compoundWarmup(definition,values[name]??{})
    if(warmup!==undefined&&typeof definition.warmup_limit==='number'&&warmup>definition.warmup_limit)return `${name}：复合依赖窗口需要 ${warmup} 根，不能超过 ${definition.warmup_limit} 根；请调整参数。`
    const meanRatio=(definition.library==='qlib_alpha158'&&definition.family==='MA')||(definition.library==='gtja191'&&definition.family==='mean_ratio')
    const identity=meanRatio?`price_mean_ratio:${effective.window}`:definition.library==='qlib_alpha158'
      ? `${definition.library}:${definition.family}:${values[name]?.window??defaults?.window?.default??''}`
      : `${definition.parameter_family??definition.canonical_name??name}:${JSON.stringify(effective)}`
    if(identities.has(identity))return '存在相同公式及窗口的重复因子，请调整窗口或移除其中一项。'
    identities.add(identity)
  }
  return ''
}

export function factorWarmupWarnings(names:readonly string[], definitions:FactorDefinition[], values:FactorParameters, count:number):string[] {
  return names.flatMap(name=>{
    const d=definitions.find(f=>f.name===name)
    if(!d)return []
    const specs=d.parameters as Record<string,Parameter>|undefined
    const key=d.library==='qlib_alpha158'?'window':name==='rsi_14'?'':name==='macd_hist_signal'?'scale_window':name==='amount_ma_ratio'?'long':'window'
    const delta=key&&specs?.[key]? (values[name]?.[key]??specs[key].default)-specs[key].default:0
    const warmup=compoundWarmup(d,values[name]??{})??(typeof d.warmup_multiplier==='number'&&typeof d.warmup_offset==='number'&&specs?.window
      ? (values[name]?.window??specs.window.default)*d.warmup_multiplier+d.warmup_offset
      : typeof d.warmup_bars==='number'?d.warmup_bars+delta:0)
    return warmup>count?[`${parameterizedFactorName(d,values[name])}至少需要 ${warmup} 根，当前请求 ${count} 根；请增加历史长度或缩短窗口。`]:[]
  })
}
