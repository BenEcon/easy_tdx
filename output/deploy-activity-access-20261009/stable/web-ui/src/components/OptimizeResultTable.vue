<script setup lang="ts">
// 网格点排名表，按 total_return 降序，最优高亮。

import type { GridPointResult } from '../types'
import { metricText } from '../metric-state'
import MetricStateNotes from './MetricStateNotes.vue'

defineProps<{
  results: GridPointResult[]
  bestIndex?: number
}>()

defineEmits<{ select: [params: Record<string, number | string>] }>()

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
          {{ metricText(r.total_return, r.metric_status?.total_return, 'percent') }}
        </td>
        <td class="num">{{ metricText(r.sharpe, r.metric_status?.sharpe) }}</td>
        <td class="num neg">{{ metricText(r.max_drawdown, r.metric_status?.max_drawdown, 'percent') }}</td>
        <td class="num">{{ r.total_trades }}</td>
        <td class="num">{{ metricText(r.win_rate, r.metric_status?.win_rate, 'percent') }}</td>
        <td><button class="view-btn" @click="$emit('select', r.params)">查看</button><MetricStateNotes :states="r.metric_status" :legacy="!r.metric_status" /></td>
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
