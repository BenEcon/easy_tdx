<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { validatePortfolioArchive, portfolioMemberArchive } from '../portfolio-archive'
import { resultBasis } from '../metric-state'
import type { Performance } from '../types'
import MacSelect from './MacSelect.vue'
import ChartFrame from './ChartFrame.vue'
import KlineChart from './KlineChart.vue'
import EquityChart from './EquityChart.vue'
import MetricTable from './MetricTable.vue'
import TradeTable from './TradeTable.vue'
import ResultDataProvenance from './ResultDataProvenance.vue'
const props=defineProps<{payload:unknown}>()
const selected=ref(0)
watch(()=>props.payload,()=>{selected.value=0})
const state=computed(()=>{try{return {saved:validatePortfolioArchive(props.payload),error:''}}catch(e){return {saved:null,error:e instanceof Error?e.message:String(e)}}})
const options=computed(()=>state.value.saved?.receipt.members.map((m,i)=>({value:i,label:`${m.key} · ${m.category}`,description:`${m.bars.length} 根原行情`}))??[])
const chosen=computed(()=>state.value.saved?portfolioMemberArchive(state.value.saved,selected.value):null)
const performance=computed(()=>state.value.saved?.receipt.result.total_performance as Performance|undefined)
</script>
<template>
  <div v-if="state.saved" class="portfolio-archive">
    <p role="status">{{ state.saved.receipt.kind==='portfolio'?'组合':'多策略' }}原档 · {{ state.saved.receipt.members.length }} 个成员。按保存时结果查看，不取数、不计算、不重新评级。</p>
    <ResultDataProvenance :evidence="state.saved.receipt.result.data_provenance" />
    <details><summary>原任务、执行版本与完整交易参数</summary><pre>{{ JSON.stringify({task_id:state.saved.receipt.task_id,execution_version:state.saved.receipt.execution_version,version_at_read:state.saved.receipt.current_execution_version,request:state.saved.receipt.request},null,2) }}</pre><p>执行版本标识不包含旧版算法；原档用于核验保存的输入与结果，不承诺可运行历史版本。</p></details>
    <ChartFrame title="原组合净值"><EquityChart :equity="state.saved.receipt.result.combined_equity" /></ChartFrame>
    <section><h4>原组合绩效</h4><MetricTable v-if="performance" :perf="performance" :states="state.saved.receipt.result.performance_basis?.metric_status" /></section>
    <section class="member-header"><h4>成员明细</h4><MacSelect v-model="selected" :options="options" aria-label="原档成员" /></section>
    <template v-if="chosen">
      <p>{{ chosen.member.symbol }} · {{ chosen.member.category }} · 资金占比 {{ (state.saved.receipt.result.equity_allocation[chosen.member.key]! *100).toFixed(2) }}% · {{ chosen.result.trades.length }} 笔成交。未封存的技术指标不补算。</p>
      <ChartFrame :key="chosen.member.key" title="成员原行情与成交"><KlineChart :bars="chosen.member.bars" :trades="chosen.result.trades" readonly-archive /></ChartFrame>
      <ChartFrame title="成员原净值"><EquityChart :equity="chosen.result.equity_curve" /></ChartFrame>
      <section><h4>成员原绩效</h4><MetricTable :perf="chosen.result.performance" :states="resultBasis(chosen.result)?.metric_status" /></section>
      <section><h4>成员原成交</h4><TradeTable :trades="chosen.result.trades" /></section>
      <details><summary>成员原来源、配置与持仓 · {{ chosen.result.positions.length }} 条</summary><pre>{{ JSON.stringify({metadata:chosen.member.metadata,config:chosen.result.config,positions:chosen.result.positions},null,2) }}</pre></details>
    </template>
  </div>
  <p v-else role="alert">{{ state.error }}。完整原始存档仍保留，未修复或重算。</p>
</template>
<style scoped>
.portfolio-archive{min-width:0;display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.portfolio-archive>*{min-width:0;max-width:100%}.member-header{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;border-top:1px solid var(--border);padding-top:16px}.member-header>:deep(*){min-width:0}p{margin:0;color:var(--text-muted);font-size:12px;line-height:1.8;overflow-wrap:anywhere}h4,summary{font-size:13px}h4{margin:0 0 8px}summary{cursor:pointer}details{padding:12px 0;border-block:1px solid var(--border)}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font-size:11px;line-height:1.8}
</style>
