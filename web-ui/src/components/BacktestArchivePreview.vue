<script setup lang="ts">
import { computed } from 'vue'
import { validateBacktestArchive } from '../backtest-archive'
import { resultBasis } from '../metric-state'
import ArchivedRadarSource from './ArchivedRadarSource.vue'
import ChartFrame from './ChartFrame.vue'
import KlineChart from './KlineChart.vue'
import EquityChart from './EquityChart.vue'
import MetricTable from './MetricTable.vue'
import TradeTable from './TradeTable.vue'
import ResultDataProvenance from './ResultDataProvenance.vue'
const props=defineProps<{payload:unknown}>()
const state=computed(()=>{
  try{return {saved:validateBacktestArchive(props.payload),error:''}}
  catch(error){return {saved:null,error: error instanceof Error?error.message:String(error)}}
})
</script>
<template>
  <div v-if="state.saved" class="backtest-archive">
    <p role="status">回测原档 · {{ state.saved.request.symbol }} · {{ state.saved.request.category }} · {{ state.saved.request.strategy }}。仅展示保存结果，不重新取数、计算或评级。</p>
    <ArchivedRadarSource :source="state.saved.radarSource" :legacy-reference="!!state.saved.metadata.original_task&&!state.saved.radarSource" />
    <ResultDataProvenance :evidence="state.saved.result.data_provenance" />
    <details><summary>原交易参数与行情来源</summary><pre>{{ JSON.stringify({execution_version:state.saved.result.execution_version??'原结果未提供执行版本',request:{...state.saved.request,ohlcv:undefined},metadata:state.saved.metadata,config:state.saved.result.config},null,2) }}</pre></details>
    <p>保存 {{ state.saved.request.ohlcv!.length }} 根原行情、{{ state.saved.result.equity_curve.length }} 条净值、{{ state.saved.result.trades.length }} 笔成交。原档未封存技术指标和评级，不按当前规则补算；没有执行版本的旧结果不视为可复现的历史算法。</p>
    <ChartFrame title="原行情与回测成交" description="直接使用原始行情和成交；不补取、不复权。"><KlineChart :bars="state.saved.request.ohlcv!" :trades="state.saved.result.trades" readonly-archive /></ChartFrame>
    <ChartFrame title="原净值曲线"><EquityChart :equity="state.saved.result.equity_curve" /></ChartFrame>
    <section><h4>原绩效</h4><MetricTable :perf="state.saved.result.performance" :states="resultBasis(state.saved.result)?.metric_status" /></section>
    <section><h4>原成交记录</h4><TradeTable :trades="state.saved.result.trades" /></section>
    <details><summary>原持仓记录 · {{ state.saved.result.positions.length }} 条</summary><pre>{{ JSON.stringify(state.saved.result.positions,null,2) }}</pre></details>
  </div>
  <p v-else role="alert">{{ state.error }}。未重算或更改原档，仍可导出核验。</p>
</template>
<style scoped>
.backtest-archive{min-width:0;display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.backtest-archive>*{min-width:0;max-width:100%}p{font-size:12px;line-height:1.8;color:var(--text-muted);margin:0;overflow-wrap:anywhere}h4,summary{font-size:13px}summary{cursor:pointer}details{padding:12px 0;border-block:1px solid var(--border)}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;font-size:11px;line-height:1.8}
</style>
