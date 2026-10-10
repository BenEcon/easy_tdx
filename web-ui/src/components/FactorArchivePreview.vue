<script setup lang="ts">
import {computed,ref} from 'vue'
import {validateFactorArchive,archivedEvaluation} from '../factor-archive'
import {factorValue,factorStatisticsLabel} from '../factor-research'
import {benchmarkLabel} from '../factor-benchmark'
import FactorDefinitionDetails from './FactorDefinitionDetails.vue'
import FactorDiagnosticChart from './FactorDiagnosticChart.vue'
import FactorSeriesComparison from './FactorSeriesComparison.vue'
import FactorValidationReport from './FactorValidationReport.vue'
import FactorHorizonComparison from './FactorHorizonComparison.vue'
import FactorCompositionResult from './FactorCompositionResult.vue'
import FactorTrackingBridge from './FactorTrackingBridge.vue'
import type {ArchiveRecord} from '../cloud-archives'
import {horizonView} from '../factor-horizons'
import ChartFrame from './ChartFrame.vue'
import MacSelect from './MacSelect.vue'
import DataGrid from './DataGrid.vue'
import {periodLabel} from '../period-comparison'
import type {Category} from '../types'
const props=defineProps<{payload:unknown;record?:ArchiveRecord}>()
const checked=computed(()=>{try{return {archive:validateFactorArchive(props.payload),error:''}}catch(e){return {archive:null,error:String(e)}}})
const archive=computed(()=>checked.value.archive),result=computed(()=>archive.value?.result),evaluation=computed(()=>archive.value?archivedEvaluation(archive.value):null)
const focus=ref(''),precision=ref<'auto'|'raw'>('auto')
const chartMode=ref('single')
const horizonChoice=ref<number|null>(null)
const displayHorizon=computed({get:()=>{
  const primary=evaluation.value?.settings.horizon??5
  return horizonChoice.value!==null&&(evaluation.value?.horizon_comparison?.horizons??[primary]).includes(horizonChoice.value)?horizonChoice.value:primary
},set:(h:number)=>{horizonChoice.value=h}})
const detailEvaluation=computed(()=>horizonView(evaluation.value,displayHorizon.value))
const names=computed(()=>result.value?.settings.factors??[])
const selected=computed(()=>names.value.includes(focus.value)?focus.value:names.value[0]??'')
const definition=computed(()=>result.value?.factor_definitions[selected.value])
const label=(key:string)=>String(result.value?.factor_definitions[key]?.display_name??key)
const rows=computed(()=>(Array.isArray(result.value?.rows)?result.value.rows:[]) as Record<string,unknown>[])
const table=computed(()=>rows.value.map(row=>({...row,...Object.fromEntries(names.value.map(n=>[n,factorValue(row[n],false,precision.value)]))})))
const report=computed(()=>detailEvaluation.value?.reports.find(r=>r.name===selected.value))
const lineage=computed(()=>{
  const value=(props.payload as Record<string,unknown>|null)?.recomputed_from
  return value&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:null
})
</script>
<template><section class="factor-preview" aria-label="只读因子研究">
  <p v-if="checked.error" role="alert">{{ checked.error }}。原始存档仍保留，未自动修复或重算。</p>
  <template v-else-if="archive&&result">
    <header><div><h3>{{ archive.title }}</h3><p>{{ new Date(archive.savedAt).toLocaleString('zh-CN') }} · {{ periodLabel(String(result.settings.category) as Category) }} · {{ ({NONE:'不复权',QFQ:'前复权',HFQ:'后复权'} as Record<string,string>)[String(result.settings.adjust)] }} · {{ archive.mode==='series'?'时间序列':'截面检验' }}</p></div><span>只读原档</span></header>
    <details v-if="lineage"><summary>重算来源 · 原始输入／当前实现</summary><p>来源存档 {{ lineage.archive_id }} · v{{ lineage.revision }}</p><p>来源摘要：{{ lineage.digest }}</p><p>只读展示已保存的重算结果；不刷新行情、不重新执行。保留原公式及迁移记录，不表示原始行情已通过真实性核验。</p><pre>{{ JSON.stringify(lineage,null,2) }}</pre></details>
    <p v-for="(reason,key) in result.errors" :key="key" role="status">{{ label(String(key)) }}：{{ reason }}</p>
    <p v-if="result.settings.benchmark">基准指数：{{ benchmarkLabel(result.settings.benchmark) }} · 独立不复权快照 · 精确日期对齐</p>
    <div class="selection"><MacSelect :model-value="selected" aria-label="存档因子" :options="names.map(n=>({value:n,label:label(n)}))" @update:model-value="focus=$event" /><MacSelect v-model="precision" aria-label="存档数值精度" :options="[{value:'auto',label:'易读精度'},{value:'raw',label:'原始精度'}]" /></div>
    <FactorDefinitionDetails v-if="definition" :definition="definition" />
    <template v-if="archive.mode==='series'">
      <MacSelect v-model="chartMode" aria-label="存档曲线布局" :options="[{value:'single',label:'单因子原值'},{value:'compare',label:'多因子分轨对比'}]" />
      <ChartFrame v-if="chartMode==='single'" title="原始因子序列" description="仅绘制保存时的数值；缺失保持为空"><FactorDiagnosticChart :precision="precision" :labels="rows.map(r=>String(r.datetime))" :series="[{name:label(selected),values:rows.map(r=>typeof r[selected]==='number'?r[selected] as number:null)}]" /></ChartFrame>
      <FactorSeriesComparison v-else :rows="rows" :names="names.filter(n=>!result?.errors[n])" :labels="Object.fromEntries(names.map(n=>[n,label(n)]))" :precision="precision" />
      <details><summary>完整序列 · {{ rows.length }} 根</summary><DataGrid :rows="table" :columns="[{key:'datetime',label:'时间'},...names.map(n=>({key:n,label:label(n)}))]" /></details>
    </template>
    <template v-else-if="evaluation">
      <FactorHorizonComparison v-if="evaluation.horizon_comparison" v-model="displayHorizon" :value="evaluation.horizon_comparison" :labels="Object.fromEntries(names.map(n=>[n,label(n)]))" @select-factor="focus=$event" />
      <FactorCompositionResult v-if="evaluation.composition" :value="evaluation.composition" :horizon="displayHorizon" :labels="Object.fromEntries(names.map(n=>[n,label(n)]))" />
      <FactorTrackingBridge v-if="record?.state==='active'" :result="evaluation" :record="record" />
      <FactorValidationReport v-if="detailEvaluation?.validation" :key="displayHorizon" :value="detailEvaluation.validation" :factor="selected" :labels="Object.fromEntries(names.map(n=>[n,label(n)]))" />
      <p>{{ evaluation.start }} — {{ evaluation.end }} · {{ evaluation.assets }} 只 · {{ evaluation.date_count }} 个观测日。回顾性检验，不是可交易净值。</p>
      <template v-if="report">
        <p>覆盖率 {{ factorValue(report.coverage,true) }} · 秩相关 {{ factorValue(report.rank_ic_mean,false,precision) }} · 信息比率 {{ factorValue(report.rank_ic_ir,false,precision) }}</p>
        <p>有效相关截面 {{ report.observations }} / {{ evaluation.date_count }}。{{ report.observations===0?'当前没有可定义的相关系数；空值不是零相关。':'' }}</p>
        <details :open="report.observations===0"><summary>未参与统计的原因</summary><p v-for="(count,reason) in report.diagnostics" :key="reason">{{ reason }}：{{ count }} 个观测日</p><p>原因可只影响分层或相关；原始有效值覆盖率与有效检验比例不同。</p></details>
        <ChartFrame title="原始秩相关序列"><FactorDiagnosticChart correlation :precision="precision" :labels="report.daily.map(d=>d.date)" :series="[{name:'秩相关',values:report.daily.map(d=>d.rank_ic)}]" /></ChartFrame>
        <ChartFrame title="原始分层平均远期收益" description="未计交易成本，不是策略净值"><FactorDiagnosticChart bar percent :precision="precision" :labels="report.layer_means.map((_,i)=>`第 ${i+1} 组`)" :series="[{name:'远期收益',values:report.layer_means}]" /></ChartFrame>
        <details><summary>每日检验明细</summary><DataGrid :columns="[{key:'date',label:'日期'},{key:'ic',label:'线性相关'},{key:'rank_ic',label:'秩相关'},{key:'n',label:'标的数'},{key:'reason',label:'说明'}]" :rows="report.daily.map(d=>({...d,ic:factorValue(d.ic,false,precision),rank_ic:factorValue(d.rank_ic,false,precision)}))" /></details>
      </template>
      <details><summary>研究边界</summary><p>统计版本：{{ factorStatisticsLabel(evaluation) }}</p><p>展示原档保存时的数值与口径，未应用当前统计规则重新计算。覆盖率不等同于有效相关截面比例。</p><p v-for="note in evaluation.limitations" :key="note">{{ note }}</p></details>
    </template>
    <details><summary>原始输入与完整配置 · {{ result.input_snapshots.length }} 个标的</summary><p>包含数据类型、索引、来源、单位核验与输入摘要。摘要用于一致性检查，不是行情真实性证明。</p><pre>{{ JSON.stringify({settings:result.settings,inputs:result.input_snapshots},null,2) }}</pre></details>
  </template>
</section></template>
<style scoped>
.factor-preview{min-width:0}header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}h3{font-size:14px;margin:0}header span{font-size:11px;color:var(--text-muted);white-space:nowrap}p{color:var(--text-muted);font-size:12px;line-height:1.8;overflow-wrap:anywhere}.selection{display:flex;gap:10px;margin:16px 0;flex-wrap:wrap}.selection>*{flex:1;min-width:150px}details{border-top:1px solid var(--border);padding:14px 0}summary{font-size:12px;cursor:pointer}details>*:not(summary){margin-top:12px}pre{font-size:11px;max-height:360px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}.factor-preview :deep(.chart-frame){margin-block:16px}
</style>
