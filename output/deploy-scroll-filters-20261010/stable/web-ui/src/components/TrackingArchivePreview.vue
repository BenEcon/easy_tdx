<script setup lang="ts">
import {computed,ref} from 'vue'
import {validateTrackingArchive} from '../tracking-archive'
import {trackingKey,trackingTitle,type BreadthFilter} from '../tracking'
import TrackingBreadth from './TrackingBreadth.vue'
import {matchesBreadthFilters} from '../tracking-filters'
import MultiPeriodOverviewTable from './MultiPeriodOverviewTable.vue'
const props=defineProps<{payload:unknown}>()
const selected=ref('')
const evidenceDetails=ref<HTMLDetailsElement>()
function openEvidence(){if(evidenceDetails.value){evidenceDetails.value.open=true;evidenceDetails.value.scrollIntoView({block:'nearest'});evidenceDetails.value.querySelector('summary')?.focus()}}
const state=computed(()=>{try{return {value:validateTrackingArchive(props.payload),error:''}}catch(e){return {value:null,error:String(e)}}})
const archive=computed(()=>state.value.value)
const breadthFilter=ref<BreadthFilter[]>([])
const visibleRows=computed(()=>archive.value?.rows.filter(r=>matchesBreadthFilters(r,breadthFilter.value))??[])
const row=computed(()=>visibleRows.value.find(r=>trackingKey(r.target)===selected.value)??visibleRows.value[0])
const labels={done:'完成',error:'失败',cancelled:'已停止',pending:'待分析',running:'分析中'}
</script>
<template><section class="tracking-archive" aria-label="追踪历史分析">
  <p v-if="state.error" role="alert">{{ state.error }}；原始文件仍可导出核验。</p>
  <template v-if="archive">
    <h3>{{ archive.group.name }}</h3><p>{{ archive.phase }} · 截止 {{ archive.cutoff }} · {{ archive.rows.length }} 个标的</p>
    <p>以下为当时保存的结果，不重新查询或计算。原始行情、复权与规则版本均保留；当前行情变化不会覆盖历史记录。</p>
    <p v-if="archive.error" role="alert">{{ archive.error }}</p>
    <p v-for="issue in archive.issues" :key="trackingKey(issue.target)">{{ trackingTitle(issue.target) }}：{{ issue.reason }}</p>
    <TrackingBreadth :rows="archive.rows" :periods="archive.periods" v-model="breadthFilter" />
    <p role="status">{{ visibleRows.length }} 个匹配标的</p>
    <div class="history-list" tabindex="0"><button v-for="r in visibleRows" :key="trackingKey(r.target)" :aria-pressed="r===row" @click="selected=trackingKey(r.target)">{{ trackingTitle(r.target) }}<span>{{ labels[r.state] }}</span></button><p v-if="!visibleRows.length">没有符合当前筛选条件的标的。</p></div>
    <section v-if="row"><h4>{{ trackingTitle(row.target) }} · {{ labels[row.state] }}</h4><p>{{ row.sources.join('、') }}</p><p v-if="row.error" role="alert">{{ row.error }}</p>
      <MultiPeriodOverviewTable v-if="row.study" :periods="archive.periods" :rows="row.study.rows" :errors="{}" :loading="false" archived @inspect="openEvidence" />
      <p v-if="row.study">规则版本：{{ row.study.rule_version }}</p>
      <details v-for="input in row.evidence?.series??[]" :key="input.category"><summary>{{ input.category }} · 原始行情 {{ input.snapshot.bars.length }} 根 · {{ row.evidence?.adjust }}</summary><pre>{{ JSON.stringify(input.snapshot,null,2) }}</pre></details>
      <details v-if="row.study" ref="evidenceDetails"><summary>完整分析依据及参数</summary><pre>{{ JSON.stringify(row.study,null,2) }}</pre></details>
    </section>
  </template>
</section></template>
<style scoped>
.tracking-archive{min-width:0}h3{font-size:15px}h4{font-size:13px}p{font-size:11px;line-height:1.8;color:var(--text-muted);overflow-wrap:anywhere}.history-list{max-height:230px;overflow:auto;border-block:1px solid var(--border);margin:14px 0}.history-list button{display:flex;justify-content:space-between;gap:15px;width:100%;white-space:normal;text-align:left;font-size:12px;padding:10px;background:transparent;border:0;border-bottom:1px solid var(--border)}button[aria-pressed=true]{background:rgba(68,150,235,.1);color:var(--accent)}button span{flex-shrink:0;color:var(--text-muted)}details{padding:12px 0;border-top:1px solid var(--border);font-size:12px}summary{cursor:pointer}pre{max-height:400px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}
</style>
