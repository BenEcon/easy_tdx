<script setup lang="ts">
import {computed} from 'vue'
import type {FactorComposition} from '../factor-composition'
import {factorValue} from '../factor-research'
import {stockDisplayName} from '../stock-history'
import ChartFrame from './ChartFrame.vue'
import FactorDiagnosticChart from './FactorDiagnosticChart.vue'
import FactorValidationReport from './FactorValidationReport.vue'
const props=defineProps<{value:FactorComposition;horizon:number;labels:Record<string,string>}>()
const current=computed(()=>props.value.horizon_comparison.results.find(r=>r.horizon===props.horizon)??props.value.horizon_comparison.results[0])
const report=computed(()=>current.value?.reports[0])
const ranking=computed(()=>[...props.value.latest].sort((a,b)=>a.score===null?(b.score===null?a.code.localeCompare(b.code):1):b.score===null?-1:b.score-a.score||a.code.localeCompare(b.code)))
</script>
<template><section class="composition-result" aria-label="固定权重组合结果">
  <header><h3>多因子组合</h3><span>固定权重 · 排名评分</span></header><p>权重与方向来自本次配置，不按检验收益拟合；评分不是交易持仓或净值。</p>
  <p v-if="value.error" role="alert" class="error">{{ value.error }}。保留全部标的和缺失评分，未改用部分因子。</p>
  <div class="weights"><span v-for="c in value.effective_components" :key="c.name">{{ labels[c.name]??c.name }} <strong>{{ c.direction===1?'正向':'反向' }} · {{ (c.normalized_weight*100).toFixed(2) }}%</strong></span></div>
  <template v-if="report">
    <p class="metrics">{{ horizon }} 个观测日 · 覆盖率 {{ factorValue(report.coverage,true) }} · 秩相关 {{ factorValue(report.rank_ic_mean) }} · 信息比率 {{ factorValue(report.rank_ic_ir) }} · 有效截面 {{ report.observations }}</p>
    <FactorValidationReport v-if="current?.validation" :value="current.validation" factor="composite_score" :labels="{composite_score:'固定权重组合'}" />
    <details class="detail" open><summary>最新组合排序 · {{ value.scores.at(-1)?.date }}</summary><div class="table-scroll" tabindex="0"><table><thead><tr><th>标的</th><th>组合评分</th><th v-for="c in value.effective_components" :key="c.name">{{ labels[c.name]??c.name }} · 贡献</th><th>说明</th></tr></thead><tbody><tr v-for="row in ranking" :key="row.code"><th>{{ stockDisplayName(row.code) }}</th><td>{{ factorValue(row.score) }}</td><td v-for="c in row.components" :key="c.name" :title="`原值 ${factorValue(c.raw,false,'raw')}；排名分 ${factorValue(c.rank,false,'raw')}`">{{ factorValue(c.contribution) }}</td><td>{{ row.reason??'完整' }}</td></tr></tbody></table></div><p>贡献之和为组合评分。原值和排名分见下方完整数据；缺失标的保留在表中。</p></details>
    <details class="detail"><summary>组合检验图表</summary><ChartFrame title="组合秩相关时间序列" description="固定配置的回顾性诊断，不是交易收益"><FactorDiagnosticChart correlation :labels="report.daily.map(d=>d.date)" :series="[{name:'组合秩相关',values:report.daily.map(d=>d.rank_ic)}]" /></ChartFrame><ChartFrame title="组合分层平均远期收益" description="未计费用、滑点和成交限制，不是可交易净值"><FactorDiagnosticChart bar percent :labels="report.layer_means.map((_,i)=>`第 ${i+1} 组`)" :series="[{name:'远期收益',values:report.layer_means}]" /></ChartFrame></details>
    <details class="detail" :open="report.observations===0"><summary>覆盖与未参与原因</summary><p v-for="(count,reason) in report.diagnostics" :key="reason">{{ reason }}：{{ count }} 个观测日</p><div class="table-scroll" tabindex="0"><table><thead><tr><th>日期</th><th>完整标的</th><th>已评分</th><th>常数组成因子</th><th>说明</th></tr></thead><tbody><tr v-for="d in value.coverage" :key="d.date"><td>{{ d.date }}</td><td>{{ d.complete_assets }}</td><td>{{ d.scored_assets }}</td><td>{{ d.constant_components.map(n=>labels[n]??n).join('、')||'—' }}</td><td>{{ d.reason??'完整' }}</td></tr></tbody></table></div></details>
  </template>
  <details class="detail"><summary>组合口径与完整数据</summary><p v-for="note in value.limitations" :key="note">{{ note }}</p><p>版本：{{ value.version }}。导出保存全部日期评分、配置和各原始因子定义。</p><pre>{{ JSON.stringify(value,null,2) }}</pre></details>
</section></template>
<style scoped>
.composition-result{border-block:1px solid var(--border);padding:20px 0;min-width:0}header{display:flex;align-items:baseline;justify-content:space-between;gap:12px}h3{font-size:14px;font-weight:600;margin:0}header span,p{font-size:11px;color:var(--text-muted)}p{line-height:1.8;overflow-wrap:anywhere}.weights{display:flex;flex-wrap:wrap;gap:8px 18px;margin:14px 0;font-size:11px}.weights strong{font-weight:500;margin-left:8px;color:var(--text)}.metrics{font-variant-numeric:tabular-nums}.detail{padding:12px 0;margin-left:10px}.detail summary{font-size:12px;cursor:pointer}.detail>*:not(summary){margin-top:12px}.table-scroll{overflow:auto;max-width:100%;max-height:330px}.table-scroll:focus-visible{outline:2px solid var(--accent)}table{width:100%;border-collapse:collapse;font-size:11px;white-space:nowrap}td,th{padding:10px 12px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums}th{font-weight:500;color:var(--text-muted)}td:first-child,th:first-child,td:last-child{text-align:left}thead th{background:var(--bg-panel);position:sticky;top:0}pre{max-height:300px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:10px}.error{color:var(--danger)}.detail :deep(.chart-frame-content){display:block}@media(max-width:480px){header{flex-wrap:wrap}.weights{display:block}.weights>span{display:block;margin-top:8px}.detail{margin-left:6px}}
</style>
