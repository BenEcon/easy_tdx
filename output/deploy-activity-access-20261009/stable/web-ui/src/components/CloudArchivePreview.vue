<script setup lang="ts">
import { computed, nextTick, onErrorCaptured, ref } from 'vue'
import type { ArchiveRecord } from '../cloud-archives'
import { validateResearchSnapshot } from '../research-snapshot-validation'
import { normalizeResearchPreferences } from '../research-preferences'
import { periodLabel } from '../period-comparison'
import ChanlunChart from './ChanlunChart.vue'
import ChartFrame from './ChartFrame.vue'
import PeriodStructureInspector from './PeriodStructureInspector.vue'
import MultiPeriodOverviewTable from './MultiPeriodOverviewTable.vue'
import { archiveStudyPreview } from '../archive-study-preview'
import type { StudyPeriod } from '../research-study'
const props = defineProps<{ record: ArchiveRecord }>()
const charts=new Map<string,InstanceType<typeof ChanlunChart>>()
const inspectors=new Map<string,InstanceType<typeof PeriodStructureInspector>>()
const renderingError = ref('')
onErrorCaptured(() => { renderingError.value='此版本无法完整绘制存档。原始内容仍保留，可展开记录或导出核验。'; return false })
const snapshotState = computed(() => {
  if (props.record.kind !== 'chart') return {snapshot:null,problem:''}
  try { const value=validateResearchSnapshot(props.record.payload); return {snapshot:{...value,preferences:normalizeResearchPreferences(value.preferences)},problem:''} }
  catch(error) { return {snapshot:null,problem:error instanceof Error?error.message:'原档格式不兼容；原始内容保留。'} }
})
const snapshot=computed(()=>snapshotState.value.snapshot)
const study = computed(() => props.record.kind === 'study' ? archiveStudyPreview(props.record.payload) : null)
const studyDetails=new Map<string,HTMLDetailsElement>()
async function inspectStudy(period:StudyPeriod){const node=studyDetails.get(period);if(node){node.open=true;await nextTick();node.scrollIntoView({block:'start'});node.querySelector('summary')?.focus()}}
</script>
<template>
  <section class="archive-preview" aria-label="云存档原始结果">
    <p>账户上传的原档，未经服务端重新核验。原行情与缠论结果不重新查询；带冻结指标的图表直接使用保存的逐根数值。</p>
    <p v-if="renderingError" role="alert">{{ renderingError }}</p>
    <template v-else-if="snapshot">
      <p>共同截止 {{ snapshot.cutoff }} · 界面 {{ snapshot.frontendVersion }} · 规则 {{ snapshot.ruleVersions.join('、') || '原档未提供统一版本' }}</p>
      <section v-for="chart in snapshot.charts" :key="chart.category">
        <ChartFrame :title="`${snapshot.title} · ${periodLabel(chart.category)}`" :description="`${chart.bars.length} 根 · ${chart.metadata.actual_adjust}`">
          <ChanlunChart :ref="el=>{if(el)charts.set(chart.category,el as InstanceType<typeof ChanlunChart>)}" :bars="chart.bars" :result="chart.result" :layers="snapshot.layers" :show-divergence-history="snapshot.history"
            :frozen-indicators="chart.frozenIndicators" readonly-archive
            :ma-periods="snapshot.preferences.ma.filter(item=>item.enabled).map(item=>item.period)" :ma-available-periods="snapshot.preferences.ma.map(item=>item.period)"
            :line-widths="snapshot.preferences.widths" :candle-transparency="snapshot.preferences.transparency" :indicator-config="snapshot.preferences.indicators" @inspect="inspectors.get(chart.category)?.inspect($event)" />
        </ChartFrame>
        <PeriodStructureInspector :ref="el=>{if(el)inspectors.set(chart.category,el as InstanceType<typeof PeriodStructureInspector>)}" :result="chart.result" :bars="chart.bars" :title="periodLabel(chart.category)" @locate="charts.get(chart.category)?.locate($event)" />
      </section>
    </template>
    <template v-else-if="study">
      <p>以下为保存时的各周期研究记录；完整参数、来源及行情包含在原始存档中。</p>
      <p v-if="!study.entries.length" role="status">原档没有研究记录；未生成空白结论，可展开完整原始存档核验。</p>
      <MultiPeriodOverviewTable v-if="study.rows.length" :periods="study.rows.map(row=>row.category as StudyPeriod)" :rows="study.rows" :errors="{}" :loading="false" archived @inspect="inspectStudy" />
      <details v-for="entry in study.entries" :key="entry.key" :ref="el=>{if(el&&entry.category)studyDetails.set(entry.category,el as HTMLDetailsElement)}"><summary>{{ entry.label }} · 原始研究记录{{ entry.problem ? '（需核验）' : '' }}</summary><p v-if="entry.problem" role="status">{{ entry.problem }}</p><pre>{{ JSON.stringify(entry.raw,null,2) }}</pre></details>
    </template>
    <p v-else role="status">{{ snapshotState.problem || '原档格式较旧或不支持当前绘图。' }} 未修改原档，可展开或导出查看。</p>
    <details><summary>完整原始存档</summary><pre>{{ JSON.stringify(record.payload,null,2) }}</pre></details>
  </section>
</template>
<style scoped>
.archive-preview{min-width:0}.archive-preview p{font-size:12px;line-height:1.8;color:var(--text-muted)}details{border-top:1px solid var(--border);padding:12px 0}summary{cursor:pointer;font-size:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:480px;overflow:auto;font-size:11px;line-height:1.8}.archive-preview>section{margin-block:20px}
</style>
