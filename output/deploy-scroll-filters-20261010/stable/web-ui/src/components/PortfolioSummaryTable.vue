<script setup lang="ts">
// 各标的绩效横向对比表。

import type { BacktestResult } from '../types'

defineProps<{
  results: Record<string, BacktestResult>
  allocation: Record<string, number>
}>()

function pct(v: number): string {
  return Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : '-'
}
function num(v: number, d = 2): string {
  return Number.isFinite(v) ? v.toFixed(d) : '-'
}
</script>

<template>
  <div class="responsive-table-scroll" tabindex="0" role="region" aria-label="组合绩效表，可横向滚动">
  <table class="summary-table">
    <thead>
      <tr>
        <th>标的</th>
        <th class="num">资金占比</th>
        <th class="num">总收益</th>
        <th class="num">最大回撤</th>
        <th class="num">夏普</th>
        <th class="num">交易数</th>
        <th class="num">胜率</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(res, key) in results" :key="key">
        <td class="sym">{{ key }}</td>
        <td class="num muted">{{ pct(allocation[key] || 0) }}</td>
        <td class="num" :class="res.performance.total_return > 0 ? 'pos' : 'neg'">
          {{ pct(res.performance.total_return) }}
        </td>
        <td class="num neg">{{ pct(res.performance.max_drawdown) }}</td>
        <td class="num">{{ num(res.performance.sharpe) }}</td>
        <td class="num">{{ res.performance.total_trades }}</td>
        <td class="num">{{ pct(res.performance.win_rate) }}</td>
      </tr>
    </tbody>
  </table>
  </div>
</template>

<style scoped>
.summary-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.summary-table th,
.summary-table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.summary-table th {
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
}
.num {
  text-align: right;
  font-family: var(--font-mono);
}
.sym {
  font-family: var(--font-mono);
  font-weight: 600;
}
.muted {
  color: var(--text-dim);
}
.pos {
  color: var(--up);
}
.neg {
  color: var(--down);
}
</style>
