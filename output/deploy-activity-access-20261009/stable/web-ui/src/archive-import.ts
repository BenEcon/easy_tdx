import { freezeArchiveDraft, validateArchiveRecord, type ArchiveDraft } from './cloud-archives.ts'
import { validateResearchSnapshot } from './research-snapshot-validation.ts'
import { archiveTime, validateArchiveBars } from './archive-data-validation.ts'
import { archiveStudyPreview } from './archive-study-preview.ts'

const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)
const periods=new Set(['DAY','WEEK','MONTH','MIN_1','MIN_5','MIN_15','MIN_30','MIN_60','MIN_120'])
function validateStudy(value:Record<string,unknown>) {
  if(value.format!=='chanlun-research-snapshot-v2'||typeof value.code!=='string'||archiveTime(value.as_of)===null
    ||!object(value.result)||!Array.isArray(value.result.rows)||!Array.isArray(value.series)||!value.series.length||value.series.length>12)throw Error('多周期备份缺少原始行情或研究结果')
  const seen=new Set<string>()
  for(const row of value.series){
    if(!object(row)||typeof row.category!=='string'||!periods.has(row.category)||seen.has(row.category)||!object(row.snapshot)
      ||!object(row.snapshot.metadata)||!Array.isArray(row.snapshot.bars)||!row.snapshot.bars.length||row.snapshot.bars.length>8000)throw Error('多周期备份的周期或行情不完整')
    seen.add(row.category)
    validateArchiveBars(row.snapshot.bars)
  }
  const rows=new Set<string>()
  for(const row of value.result.rows){
    if(!object(row)||typeof row.category!=='string'||!periods.has(row.category)||rows.has(row.category)
      ||(row.error!==undefined&&typeof row.error!=='string')||(!row.error&&!seen.has(row.category)))throw Error('多周期研究结果的周期与原行情不匹配')
    rows.add(row.category)
  }
  if(!rows.size)throw Error('多周期备份未包含研究记录')
}

export interface PreparedArchiveImport { draft:ArchiveDraft; description:string; warnings:string[] }
/** Validate without normalizing the archived payload or substituting current settings/results. */
export function prepareArchiveImport(value:unknown,filename:string):PreparedArchiveImport {
  if(!object(value))throw Error('请选择本地研究快照、多周期研究备份或云存档导出的 JSON 文件')
  const envelope='payload' in value ? validateArchiveRecord(value,true) : null
  const source=envelope?.payload??value
  if(!object(source))throw Error('备份正文不是有效的研究记录')
  // Imported account IDs are never permissions and are not uploaded as user data.
  const {owner:_owner,...payload}=source
  const warnings=['内容由文件提供，未重新计算或验证其行情及分析真实性。导入创建独立副本，不覆盖同名云存档。']
  if(_owner!==undefined)warnings.push('已移除原浏览器账户绑定字段；新副本仅归当前登录账户。')
  let kind:ArchiveDraft['kind'],description:string
  if(payload.schema===1){
    validateResearchSnapshot(payload)
    kind='chart'
    const charts=payload.charts as Array<{category:string;bars:unknown[];frozenIndicators?:unknown}>
    description=charts.map(chart=>`${chart.category} · ${chart.bars.length} 根`).join(' / ')
    if(charts.some(chart=>chart.frozenIndicators===undefined))warnings.push('旧档缺少冻结指标，未补算或补造原版数值；查看时会明确标注这一限制。')
  }else if(payload.format==='chanlun-research-snapshot-v2'){
    validateStudy(payload);kind='study';description=`${(payload.series as unknown[]).length} 个周期原始行情 · ${String(payload.as_of)}`
    const incomplete=archiveStudyPreview(payload)?.entries.filter(entry=>entry.problem).length??0
    if(incomplete)warnings.push(`${incomplete} 条研究记录的表格字段不完整；导入后会标明原因并保留原始记录，不补算或修复。`)
  }else throw Error('不支持此备份版本，未修改文件；请保留原件')
  if(envelope&&envelope.kind!==kind)throw Error('云存档类型与正文不一致')
  const name=envelope?.name??(typeof payload.name==='string'?payload.name:typeof payload.title==='string'?payload.title:filename.replace(/\.json$/i,''))
  const note=envelope?.note??(typeof payload.note==='string'?payload.note:'')
  const draft=freezeArchiveDraft({kind,name,note,payload})
  return {draft,description,warnings}
}
