import {archiveObject as object,archiveTime} from './archive-data-validation.ts'

export const benchmarkOptions=[
  {value:'SH:000001',label:'上证指数 · 000001'},
  {value:'SZ:399001',label:'深证成指 · 399001'},
  {value:'SH:000300',label:'沪深300 · 000300'},
  {value:'SZ:399006',label:'创业板指 · 399006'},
]
const fields=['benchmark_open','benchmark_close']
export function needsBenchmark(names:string[],definitions:Record<string,unknown>[]):boolean {
  return definitions.some(d=>names.includes(String(d.name))&&Array.isArray(d.inputs)&&d.inputs.some(k=>fields.includes(String(k))))
}
export const benchmarkLabel=(symbol:unknown)=>benchmarkOptions.find(o=>o.value===symbol)?.label??'未选择基准'

export function validateBenchmarkPool(inputs:Record<string,unknown>[],selected:unknown):void {
  const digests=new Set<string>()
  for(const input of inputs){
    validateBenchmarkInput(input,selected)
    const attrs=input.attrs
    if(object(attrs)&&object(attrs.factor_benchmark)&&object(attrs.factor_benchmark.snapshot))
      digests.add(String(attrs.factor_benchmark.snapshot.digest))
  }
  if(digests.size>1)throw Error('股票池混用了不同版本的基准指数快照')
}

/** Read-only structural/pair checks; digest authenticity remains a server check. */
export function validateBenchmarkInput(input:Record<string,unknown>,selected:unknown):void {
  const fail=()=>{throw Error('基准指数原档不完整或与研究配置不一致')}
  if(!object(input.attrs)||!Array.isArray(input.columns)||!Array.isArray(input.rows))return fail()
  const attrs=input.attrs,columns=input.columns,rows=input.rows
  const contract=attrs.factor_benchmark
  if(contract===undefined){
    if(columns.some(k=>fields.includes(String(k))))return fail()
    if(selected!==undefined&&selected!==null){
      const errors=attrs.factor_input_errors
      if(!object(errors)||!fields.every(k=>typeof errors[k]==='string'&&errors[k]))return fail()
    }
    return
  }
  if(!object(contract)||contract.version!=='factor-benchmark-v1'||contract.alignment!=='exact_observation_time_no_fill'||contract.symbol!==selected||!benchmarkOptions.some(o=>o.value===selected)||!fields.every(k=>columns.includes(k)))return fail()
  const knownName=benchmarkLabel(selected).split(' · ')[0]
  if(contract.name!==knownName||!object(contract.snapshot))return fail()
  const nested=contract.snapshot
  if(nested.version!=='factor-input-v1'||nested.symbol!==selected||!object(nested.attrs)||'factor_benchmark' in nested.attrs||!Array.isArray(nested.columns)||!Array.isArray(nested.rows)||nested.rows.length<1||nested.rows.length>800||nested.columns.some(k=>fields.includes(String(k)))||typeof nested.digest!=='string'||!/^[a-f0-9]{64}$/.test(nested.digest))return fail()
  const meta=nested.attrs.snapshot_metadata,stockMeta=attrs.snapshot_metadata
  if(!object(meta)||!object(stockMeta)||!object(meta.instrument)||meta.instrument.kind!=='index'||`${meta.instrument.market}:${meta.instrument.code}`!==selected||!['MAC_INDEX','TDX_INDEX'].includes(String(meta.source))||meta.actual_adjust!=='NONE'||meta.requested_adjust!=='NONE'||meta.category!==stockMeta.category||meta.bar_time!=='end'||stockMeta.bar_time!=='end')return fail()
  const points=(value:Record<string,unknown>)=>{
    const cols=value.columns as unknown[],data=value.rows as unknown[]
    const key=cols.includes('datetime')?'datetime':'date',pos=cols.indexOf(key),closed=cols.indexOf('is_closed')
    let prior=-Infinity
    return data.map((r,i)=>{
      if(!Array.isArray(r)||r.length!==cols.length||r[closed]!==true)return fail()
      const raw=pos<0&&object(value.index)&&Array.isArray(value.index.values)?value.index.values[i]:r[pos]
      const text=object(raw)?raw.timestamp??raw.datetime??raw.date:raw
      const time=archiveTime(text)
      if(time===null||time<=prior)return fail()
      prior=time;return {time,row:r}
    })
  }
  const benchmark=new Map(points(nested).map(p=>[p.time,p.row]))
  const open=nested.columns.indexOf('open'),close=nested.columns.indexOf('close')
  if(open<0||close<0)return fail()
  for(const r of benchmark.values())if(![r[open],r[close]].every(v=>typeof v==='number'&&Number.isFinite(v)&&v>0))return fail()
  let matched=0
  for(const p of points(input)){
    const expected=benchmark.get(p.time)
    if(expected)matched++
    for(const [i,k] of fields.entries()){
      const actual=p.row[columns.indexOf(k)]
      if(expected?actual!==expected[i===0?open:close]:!(object(actual)&&actual.special==='NaN'))return fail()
    }
  }
  if(matched===0||contract.matched_rows!==matched||contract.missing_rows!==rows.length-matched)return fail()
}
