<script setup lang="ts">
// 网格点排名表，按 total_return 降序，最优高亮。

import type { GridPointResult } from '../types'

defineProps<{
  results: GridPointResult[]
  bestIndex?: number
}>()

defineEmits<{ select: [params: Record<string, number | string>] }>()

function pct(v: number | null): string {
  return v !== null && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : '-'
}
function num(v: number | null, d = 2): string {
  return v !== null && Number.isFinite(v) ? v.toFixed(d) : '-'
}
</script>

<template>
  <div class="responsive-table-scroll" tabindex="0" role="region" aria-label="寻优结果表，可横向滚动">
  <table class="opt-table">
    <thead>
      <tr>
        <th>#</th>
        <th>参数</th>
        <th class="num">总收益</th>
        <th class="num">夏普</th>
        <th class="num">最大回撤</th>
        <th class="num">交易数</th>
        <th class="num">胜率</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(r, i) in results" :key="i" :class="{ best: i === bestIndex }">
        <td class="rank">{{ i + 1 }}</td>
        <td class="params">{{ JSON.stringify(r.params) }}</td>
        <td class="num" :class="r.total_return !== null && r.total_return > 0 ? 'pos' : 'neg'">
          {{ pct(r.total_return) }}
        </td>
        <td class="num">{{ num(r.sharpe) }}</td>
        <td class="num neg">{{ pct(r.max_drawdown) }}</td>
        <td class="num">{{ r.total_trades }}</td>
        <td class="num">{{ pct(r.win_rate) }}</td>
        <td><button class="view-btn" @click="$emit('select', r.params)">查看</button></td>
      </tr>
    </tbody>
  </table>
  </div>
</template>

<style scoped>
.opt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.opt-table th,
.opt-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.opt-table th {
  color: var(--text-dim);
  font-size: 12px;
  position: sticky;
  top: 0;
  background: var(--bg-panel);
}
.num {
  text-align: right;
  font-family: var(--font-mono);
}
.params {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
}
.rank {
  color: var(--text-dim);
  width: 32px;
}
.best {
  background: rgba(74, 158, 255, 0.08);
}
.best .rank {
  color: var(--accent);
  font-weight: 700;
}
.pos {
  color: var(--up);
}
.neg {
  color: var(--down);
}
.view-btn {
  font-size: 11px;
  padding: 2px 8px;
}
</style>
