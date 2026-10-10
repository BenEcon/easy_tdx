<script setup lang="ts">
// 多 task 指标横向对比表（每个 task 一列或一行）。

import type { BacktestResult } from '../types'
import { metricText, resultBasis } from '../metric-state'
import MetricStateNotes from './MetricStateNotes.vue'
import PerformanceContextNote from './PerformanceContextNote.vue'
import { computed } from 'vue'
import { comparisonWarnings, performanceContext } from '../performance-context'

const props = defineProps<{
  items: Array<{ label: string; result: BacktestResult }>
}>()

interface Row {
  label: string
  key: keyof BacktestResult['performance']
  format: 'percent' | 'ratio' | 'int'
}

const ROWS: Row[] = [
  { label: '总收益', key: 'total_return', format: 'percent' },
  { label: '年化收益', key: 'annual_return', format: 'percent' },
  { label: '夏普', key: 'sharpe', format: 'ratio' },
  { label: '最大回撤', key: 'max_drawdown', format: 'percent' },
  { label: '胜率', key: 'win_rate', format: 'percent' },
  { label: '盈亏比', key: 'profit_factor', format: 'ratio' },
  { label: '交易数', key: 'total_trades', format: 'int' },
  { label: '波动率', key: 'volatility', format: 'percent' },
]

function fmt(row: Row, result: BacktestResult): string {
  return metricText(result.performance[row.key], resultBasis(result)?.metric_status?.[row.key], row.format)
}
const warnings = computed(() => comparisonWarnings(props.items.map(item => item.result)))
</script>

<template>
  <p v-for="warning in warnings" :key="warning" class="comparison-note" role="status">{{ warning }}</p>
  <div class="responsive-table-scroll" tabindex="0" role="region" aria-label="指标对比表，可横向滚动">
  <table class="compare-table">
    <thead>
      <tr>
        <th>指标</th>
        <th v-for="item in props.items" :key="item.label" class="col">{{ item.label }}</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td class="metric-label">计算口径</td>
        <td v-for="item in props.items" :key="item.label">{{ performanceContext(resultBasis(item.result)).label }}</td>
      </tr>
      <tr v-for="row in ROWS" :key="row.key">
        <td class="metric-label">{{ row.label }}</td>
        <td v-for="item in props.items" :key="item.label" class="num">
          {{ fmt(row, item.result) }}
        </td>
      </tr>
    </tbody>
  </table>
  </div>
  <section v-for="item in props.items" :key="item.label" :aria-label="item.label">
    <h4 class="context-label">{{ item.label }}</h4>
    <PerformanceContextNote :basis="resultBasis(item.result)" />
    <MetricStateNotes :states="resultBasis(item.result)?.metric_status" :legacy="!resultBasis(item.result)?.metric_status" />
  </section>
</template>

<style scoped>
.comparison-note{font-size:12px;color:var(--text-muted);line-height:1.7;margin:0 0 10px;overflow-wrap:anywhere}
.context-label{font-size:12px;font-weight:500;color:var(--text);margin:16px 0 0;overflow-wrap:anywhere}
.compare-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.compare-table th,
.compare-table td {
  padding: 7px 12px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.compare-table th {
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
}
.compare-table th.col {
  color: var(--accent);
  font-family: var(--font-mono);
  white-space: nowrap;
}
.metric-label {
  color: var(--text-muted);
  white-space: nowrap;
}
.num {
  font-family: var(--font-mono);
  text-align: right;
  white-space: nowrap;
}
</style>
