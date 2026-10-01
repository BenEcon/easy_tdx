<script setup lang="ts">
// 多 task 指标横向对比表（每个 task 一列或一行）。

import type { BacktestResult } from '../types'

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

function fmt(row: Row, v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return '-'
  if (row.format === 'percent') return `${(v * 100).toFixed(2)}%`
  if (row.format === 'int') return String(Math.round(v))
  return v.toFixed(3)
}
</script>

<template>
  <div class="responsive-table-scroll" tabindex="0" role="region" aria-label="指标对比表，可横向滚动">
  <table class="compare-table">
    <thead>
      <tr>
        <th>指标</th>
        <th v-for="item in props.items" :key="item.label" class="col">{{ item.label }}</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="row in ROWS" :key="row.key">
        <td class="metric-label">{{ row.label }}</td>
        <td v-for="item in props.items" :key="item.label" class="num">
          {{ fmt(row, item.result.performance[row.key] as number) }}
        </td>
      </tr>
    </tbody>
  </table>
  </div>
</template>

<style scoped>
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
}
.metric-label {
  color: var(--text-muted);
  white-space: nowrap;
}
.num {
  font-family: var(--font-mono);
  text-align: right;
}
</style>
