<script setup lang="ts">
import { computed } from 'vue'
import type { PerformanceBasis } from '../types'
import type { MetricStates } from '../metric-state'
import { performanceContext } from '../performance-context'
import { formatMarketTime } from '../bar-time'

const props = defineProps<{ basis?: PerformanceBasis | null; states?: MetricStates }>()
const context = computed(() => performanceContext(props.basis, props.states))
const labels: Record<string, string> = { DAY: '日', WEEK: '周', MONTH: '月', SEASON: '季', YEAR: '年' }
</script>

<template>
  <details class="performance-context">
    <summary>
      <span>{{ context.label }}</span>
      <span v-if="basis" class="sample">{{ labels[basis.sample_category] || basis.sample_category }}收益采样 · {{ basis.return_count }} 个收益样本</span>
      <span v-else class="sample">保存值未自动重算</span>
    </summary>
    <div class="context-body">
      <p v-if="context.reason">{{ context.reason }}</p>
      <p v-if="basis?.scope === 'input_sampling_schedule'">此处是寻优输入采样范围；评级另核验每个候选的指标状态。</p>
      <dl v-if="basis">
        <dt>计算版本</dt><dd>{{ basis.contract_version }} · {{ basis.metric_contract || '指标版本未记录' }}</dd>
        <dt>采样范围</dt><dd>{{ formatMarketTime(basis.sample_start || '') || '未记录' }} — {{ formatMarketTime(basis.sample_end || '') || '未记录' }}</dd>
        <dt>年化期数</dt><dd>{{ basis.annual_periods }}</dd>
        <dt>无风险利率</dt><dd>{{ typeof basis.risk_free_rate === 'number' ? `${(basis.risk_free_rate * 100).toFixed(2)}%` : '未记录' }}</dd>
      </dl>
      <p>重新运行会生成新结果，不覆盖此处保存值。版本和采样范围不同的结果不宜直接排名。</p>
    </div>
  </details>
</template>

<style scoped>
.performance-context{min-width:0;font-size:12px;color:var(--text-muted);line-height:1.65}
summary{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 12px;cursor:pointer;min-height:32px;padding:5px 0;list-style:none}
summary::before{content:'›';color:var(--text-dim);transition:transform .15s}
details[open]>summary::before{transform:rotate(90deg)}summary>span:first-of-type{color:var(--text)}
.sample{font-size:11px}.context-body{padding:4px 0 4px 18px;overflow-wrap:anywhere}
p{margin:5px 0}dl{display:grid;grid-template-columns:80px minmax(0,1fr);gap:5px 12px;margin:8px 0}dt{color:var(--text-dim)}dd{margin:0;font-variant-numeric:tabular-nums}
@media(max-width:480px){dl{grid-template-columns:1fr;gap:2px}dd{padding-bottom:6px}.sample{flex-basis:100%;padding-left:18px}}
@media(prefers-reduced-motion:reduce){summary::before{transition:none}}
</style>
