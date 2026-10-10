import { archiveObject, archiveNumber, archiveTime } from './archive-data-validation.ts'

type RecordValue = Record<string, unknown>
type Validator = (value: unknown, path: string) => void
const fail = (path: string): never => { throw Error(`存档结构字段不兼容：${path}；原始记录未修改，未重新计算。`) }
const object = (value: unknown, path: string): RecordValue => {
  if (!archiveObject(value)) return fail(path)
  return value
}
const text: Validator = (v,p) => { if (typeof v !== 'string') fail(p) }
const number: Validator = (v,p) => { if (!archiveNumber(v)) fail(p) }
const boolean: Validator = (v,p) => { if (typeof v !== 'boolean') fail(p) }
const index: Validator = (v,p) => { if (!archiveNumber(v) || !Number.isSafeInteger(v) || v < 0) fail(p) }
const time: Validator = (v,p) => { if (archiveTime(v) === null) fail(p) }
const nullable = (check: Validator): Validator => (v,p) => { if (v !== null) check(v,p) }
const choice = (...values: string[]): Validator => (v,p) => { if (typeof v !== 'string' || !values.includes(v)) fail(p) }
const direction = choice('up','down')
const list = (check: Validator): Validator => (value,path) => {
  if (!Array.isArray(value)) return fail(path)
  value.forEach((item,i) => check(item,`${path}[${i}]`))
}
const map = (check: Validator): Validator => (value,path) => {
  for (const [key,item] of Object.entries(object(value,path))) check(item,`${path}.${key}`)
}
const optional = (row: RecordValue,path: string,key: string,check: Validator) => {
  if (row[key] !== undefined) check(row[key],`${path}.${key}`)
}
const fields = (row: RecordValue,path: string,keys: string[],check: Validator) => {
  for (const key of keys) check(row[key],`${path}.${key}`)
}
const optionalFields = (row: RecordValue,path: string,keys: string[],check: Validator) => {
  for (const key of keys) optional(row,path,key,check)
}
const range = (row: RecordValue,path: string,low = 'low',high = 'high') => {
  fields(row,path,[low,high],number)
  if (Number(row[low]) > Number(row[high])) fail(`${path}.${low}/${high}`)
}
const dates = (row: RecordValue,path: string) => {
  fields(row,path,['start_date','end_date'],nullable(time))
  if (row.start_date !== null && row.end_date !== null && archiveTime(row.start_date)! > archiveTime(row.end_date)!) fail(`${path}.start_date/end_date`)
}
const pair: Validator = (v,p) => {
  list(number)(v,p)
  if ((v as number[]).length !== 2 || (v as number[])[0]! > (v as number[])[1]!) fail(p)
}
const feature: Validator = (v,p) => {
  const row = object(v,p)
  range(row,p); fields(row,p,['high_pen','low_pen'],index)
  list(index)(row.pen_indices,`${p}.pen_indices`)
}
const segment: Validator = (v,p) => {
  const row = object(v,p)
  index(row.index,`${p}.index`); direction(row.direction,`${p}.direction`)
  fields(row,p,['start_date','end_date'],time); dates(row,p); range(row,p)
  optionalFields(row,p,['start_value','end_value'],number)
  optionalFields(row,p,['done','structurally_confirmed'],boolean)
  optional(row,p,'confirmed_date',nullable(time)); optional(row,p,'confirmed_index',nullable(index))
  optional(row,p,'evidence',(value,path) => {
    if (value === null) return
    const evidence = object(value,path)
    text(evidence.case,`${path}.case`)
    fields(evidence,path,['start_pen','end_pen'],index)
    optional(evidence,path,'supporting_pen',nullable(index))
    optionalFields(evidence,path,['features','reverse_features'],nullable(list(feature)))
    optional(evidence,path,'special_inclusion',boolean)
  })
}
const centre: Validator = (v,p) => {
  const row = object(v,p)
  fields(row,p,['index','line_count'],index); boolean(row.done,`${p}.done`)
  range(row,p,'zd','zg'); range(row,p,'dd','gg'); dates(row,p)
  optionalFields(row,p,['state','relation_at_formation','relation_current'],text)
  optionalFields(row,p,['formed_date','exited_date'],nullable(time))
  optionalFields(row,p,['formed_index','exited_index'],nullable(index))
  optionalFields(row,p,['seed_segments','member_segments'],nullable(list(index)))
  optional(row,p,'transitions',nullable(list((value,path) => {
    const event = object(value,path)
    text(event.state,`${path}.state`); index(event.segment_index,`${path}.segment_index`); time(event.known_date,`${path}.known_date`)
  })))
  optional(row,p,'relation_history',nullable(list((value,path) => {
    const event = object(value,path)
    time(event.known_date,`${path}.known_date`); text(event.relation,`${path}.relation`)
    index(event.previous_centre,`${path}.previous_centre`); boolean(event.both_exited,`${path}.both_exited`)
    nullable(pair)(event.envelope_overlap,`${path}.envelope_overlap`)
  })))
}
const event: Validator = (v,p) => {
  const row = object(v,p)
  fields(row,p,['signal_date','detected_date'],time); text(row.status,`${p}.status`)
  optionalFields(row,p,['preliminary_date','confirmed_date','invalidated_date'],nullable(time))
  optionalFields(row,p,['type','failure_reason'],text)
}
const check: Validator = (v,p) => {
  const row = object(v,p)
  text(row.gate,`${p}.gate`); boolean(row.passed,`${p}.passed`)
  map((value,path) => { if (value !== null && typeof value !== 'string' && typeof value !== 'boolean' && !archiveNumber(value)) fail(path) })(row.values,`${p}.values`)
  optional(row,p,'dates',map(time))
}
const audit: Validator = (v,p) => {
  const row = object(v,p)
  map(time)(row.dates,`${p}.dates`); list(check)(row.checks,`${p}.checks`); boolean(row.closed,`${p}.closed`)
}
const diagnostic: Validator = (v,p) => {
  const row = object(v,p)
  audit(v,p); direction(row.direction,`${p}.direction`); text(row.status,`${p}.status`)
  optional(row,p,'family',text); optional(row,p,'first_candidate_index',nullable(index))
  list((value,path) => {
    const rejection = object(value,path)
    fields(rejection,path,['from_date','through_date'],time)
    list(text)(rejection.gates,`${path}.gates`)
  })(row.rejections,`${p}.rejections`)
  optional(row,p,'comparisons',nullable(list((value,path) => {
    const comparison = object(value,path)
    audit(value,path); text(comparison.mode,`${path}.mode`)
    fields(comparison,path,['research_only','passed'],boolean)
    optional(comparison,path,'events',nullable(list(event)))
  })))
}
const divergence: Validator = (v,p) => {
  const row = object(v,p)
  choice('bi','pz','qs','macd','macd_wave','macd_wave_nonstandard','macd_wave_special')(row.type,`${p}.type`)
  boolean(row.bc,`${p}.bc`); text(row.msg,`${p}.msg`)
  // The current renderer labels an absent direction as a bottom. Never guess for an archive.
  direction(row.direction,`${p}.direction`)
  fields(row,p,['curr_date','prev_date'],nullable(time))
  optionalFields(row,p,['detected_date','confirmed_date','preliminary_date','invalidated_date'],nullable(time))
  optionalFields(row,p,['signal_index','reference_index','detected_index','confirmed_index','preliminary_index','invalidated_index'],nullable(index))
  optional(row,p,'status',choice('candidate','confirmed','superseded'))
  optional(row,p,'failure_reason',text)
  optional(row,p,'intervals',nullable(map(time)))
  optional(row,p,'evidence',nullable(map(number)))
  const evidence = archiveObject(row.evidence) ? row.evidence : {}
  if (evidence.reverse_pen_first_formed === 1) fields(evidence,`${p}.evidence`,['reverse_pen_start_price','reverse_pen_end_price'],number)
  optional(row,p,'related_events',nullable(list(event)))
  optional(row,p,'failure_audit',(value,path) => {
    if (value === null) return
    const failure = object(value,path)
    // The server's empty checkpoint is an empty object, not a failed check.
    if (Object.keys(failure).length) audit(value,path)
  })
}
const signal: Validator = (v,p) => {
  const row = object(v,p)
  choice('1buy','2buy','3buy','1sell','2sell','3sell')(row.type,`${p}.type`)
  text(row.msg,`${p}.msg`); nullable(time)(row.date,`${p}.date`)
  optional(row,p,'confirmed_date',nullable(time)); optional(row,p,'confirmed_index',nullable(index)); optional(row,p,'source',text)
  optional(row,p,'evidence',(value,path) => {
    if (value === null) return
    const evidence = object(value,path)
    optionalFields(evidence,path,['first_segment','rebound_segment','departure_segment','return_segment','a_segment','c_segment','centre_segment_count'],index)
    optionalFields(evidence,path,['zd','zg','area_ratio'],number)
    optional(evidence,path,'first_return',boolean); optional(evidence,path,'strength',text)
  })
}
const consolidation: Validator = (v,p) => {
  const row = object(v,p)
  fields(row,p,['start_date','end_date'],time); dates(row,p); range(row,p,'lower','upper')
  list(index)(row.pen_indices,`${p}.pen_indices`); boolean(row.confirmed,`${p}.confirmed`)
  optional(row,p,'source',text); optional(row,p,'eligible_for_trading',boolean)
}

/** Current archive chart/inspector consumption contract. No recalculation or JSON rewriting.
 * Unrendered recursion trees/unknown fields stay opaque in the original record;
 * validating these fields does not certify analysis truth or every historical schema.
 */
export function validateArchiveChartResult(value: unknown, path = 'result'): void {
  const row = object(value,path)
  fields(row,path,['code','frequency'],text)
  list((v,p) => { segment(v,p); boolean(object(v,p).done,`${p}.done`) })(row.bis,`${path}.bis`)
  list(segment)(row.xds,`${path}.xds`); list(centre)(row.zss,`${path}.zss`)
  list(divergence)(row.bcs,`${path}.bcs`); list(signal)(row.mmds,`${path}.mmds`)
  optional(row,path,'unfinished_xd',nullable(segment))
  optional(row,path,'structural_centres',nullable(list(centre)))
  optional(row,path,'pen_consolidations',nullable(list(consolidation)))
  optional(row,path,'wave_diagnostics',nullable(list(diagnostic)))
  optional(row,path,'macd',(value,p) => {
    if (value === null) return
    const macd = object(value,p)
    fields(macd,p,['dif','dea','hist'],list(nullable(number)))
    if ((macd.dif as unknown[]).length !== (macd.dea as unknown[]).length || (macd.dif as unknown[]).length !== (macd.hist as unknown[]).length) fail(p)
  })
}
