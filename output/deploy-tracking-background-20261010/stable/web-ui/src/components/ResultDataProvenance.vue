<script setup lang="ts">
import DataProvenance from './DataProvenance.vue'
import ValuationSamplingDetails from './ValuationSamplingDetails.vue'
import { formatMarketTime } from '../bar-time'
import type { ResultDataProvenance } from '../types'
defineProps<{ evidence?: ResultDataProvenance | null }>()
const sampleLabels: Record<string, string> = { DAY: '日', WEEK: '周', MONTH: '月', SEASON: '季', YEAR: '年' }
</script>

<template>
  <details v-if="evidence" class="result-provenance">
    <summary><strong>本次计算数据</strong><span>{{ evidence.datasets.length }} 组输入 · 参数随结果固定</span></summary>
    <div class="result-data-body">
      <section v-if="evidence.performance_basis" class="performance-basis">
        <h4>绩效计算口径</h4>
        <p>{{ sampleLabels[evidence.performance_basis.sample_category] || evidence.performance_basis.sample_category }}收益采样 · 每年 {{ evidence.performance_basis.annual_periods }} 期 · {{ evidence.performance_basis.return_count }} 个收益样本</p>
        <p v-if="evidence.performance_basis.sample_start">{{ formatMarketTime(evidence.performance_basis.sample_start) }} — {{ formatMarketTime(evidence.performance_basis.sample_end || '') }}</p>
        <p v-if="evidence.performance_basis.unavailable_reason" role="status">{{ evidence.performance_basis.unavailable_reason }}</p>
        <p v-for="note in evidence.performance_basis.warnings" :key="note">{{ note }}</p>
        <p v-if="evidence.performance_basis.scope === 'input_sampling_schedule'">此处为寻优输入的共同采样范围；每个策略的不可用指标不计为零。</p>
        <ValuationSamplingDetails :basis="evidence.performance_basis" />
      </section>
      <p v-if="evidence.alignment === 'independent_equity_union_forward_fill'" class="alignment-note">各标的独立回测；组合净值按日期并集延续上次估值，不代表缺失日期存在真实行情。</p>
      <section v-for="(dataset, index) in evidence.datasets" :key="index">
        <h4>{{ dataset.symbol || '内联行情' }}<span>{{ dataset.label }}</span></h4>
        <DataProvenance :metadata="dataset.metadata" :count="dataset.bar_count" />
      </section>
      <details class="request-details"><summary>查看本次提交参数</summary><pre>{{ JSON.stringify(evidence.request, null, 2) }}</pre></details>
    </div>
  </details>
</template>

<style scoped>
.performance-basis{font-size:11px;line-height:1.7;color:var(--text-muted);overflow-wrap:anywhere}.performance-basis h4{color:var(--text);margin-bottom:6px}.performance-basis p{margin:4px 0}
.result-provenance{border-bottom:1px solid var(--border);padding:10px 0;margin-bottom:16px;font-size:12px;min-width:0}.result-provenance>summary{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;list-style:none;cursor:pointer;min-height:32px}.result-provenance>summary:before{content:'›';color:var(--text-muted);transition:transform .15s}.result-provenance[open]>summary:before{transform:rotate(90deg)}summary strong{font-weight:500}summary span{color:var(--text-muted);font-size:11px}.result-data-body{padding:10px 0 6px 22px}h4{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;font-weight:500;margin:12px 0 0}h4 span,.alignment-note{color:var(--text-muted);font-weight:400;font-size:11px;line-height:1.7}.request-details{margin:14px 0;color:var(--text-muted)}.request-details summary{cursor:pointer;padding:6px 0}.request-details pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;line-height:1.7;padding:8px 0;font-variant-numeric:tabular-nums}@media(max-width:600px){.result-data-body{padding-left:12px}summary span{flex-basis:100%;margin-left:22px}}@media(prefers-reduced-motion:reduce){.result-provenance>summary:before{transition:none}}
</style>
