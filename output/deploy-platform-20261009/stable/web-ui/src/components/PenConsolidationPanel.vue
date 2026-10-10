<script setup lang="ts">
import { structureDate } from '../structure-display'
defineProps<{
  areas: Array<{ pen_indices: number[]; start_date: string; end_date: string; lower: number; upper: number; confirmed: boolean }>
}>()
</script>

<template>
  <details class="research-panel consolidation-panel research-hierarchy">
    <summary>
      <strong>三笔盘整 <small>{{ areas.length }} 组</small></strong>
      <span>笔级重叠 · 非中枢</span>
    </summary>
    <div class="research-panel-body">
      <div class="consolidation-boundary">
        <strong>不等同于中枢</strong>
        <p>这里展示三笔的价格重叠区间，与基础中枢分开识别，不作为独立交易依据。</p>
      </div>
      <table class="consolidation-table" role="table" aria-label="三笔盘整区间">
        <thead role="rowgroup"><tr role="row"><th scope="col" role="columnheader">区间 / 时间</th><th scope="col" role="columnheader">重叠价格</th><th scope="col" role="columnheader">来源笔</th><th scope="col" role="columnheader">确认状态</th></tr></thead>
        <tbody role="rowgroup">
          <tr v-for="(area, index) in areas" :key="area.pen_indices.join('-')" role="row" :class="{ pending: !area.confirmed }">
            <th scope="row" role="rowheader" class="consolidation-identity"><strong><span>{{ String(index + 1).padStart(2, '0') }}</span>盘整区间</strong><div class="consolidation-dates"><time>{{ structureDate(area.start_date) }}</time><span aria-hidden="true">→</span><time>{{ structureDate(area.end_date) }}</time></div></th>
            <td role="cell" class="consolidation-price"><span class="mobile-label">重叠价格</span><span>{{ area.lower.toFixed(2) }} <span class="range-separator">—</span> {{ area.upper.toFixed(2) }}</span></td>
            <td role="cell" class="consolidation-pens"><span class="mobile-label">来源笔</span><span class="pen-values">{{ area.pen_indices.map(pen => pen + 1).join(' · ') }}</span></td>
            <td role="cell" class="consolidation-state" :class="{ confirmed: area.confirmed }"><strong><i aria-hidden="true"></i>{{ area.confirmed ? '已确认' : '进行中' }}</strong><small>{{ area.confirmed ? '三笔均已确认' : '末笔待确认 · 区间可变化' }}</small></td>
          </tr>
        </tbody>
      </table>
    </div>
  </details>
</template>

<style scoped>
.consolidation-panel > summary strong small { margin-left: 8px; color: var(--text-dim); font-size: 11px; font-weight: 400; }
.consolidation-boundary { display: flex; align-items: baseline; gap: 12px; margin: 8px 0 20px; }
.consolidation-boundary strong { flex-shrink: 0; font-size: 12px; font-weight: 550; color: #c1cad7; }
.consolidation-boundary p { margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.8; }
.consolidation-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-variant-numeric: tabular-nums; }
.consolidation-table th, .consolidation-table td { padding: 16px 12px; text-align: left; vertical-align: middle; border-bottom: 1px solid rgba(255,255,255,.055); overflow-wrap: anywhere; }
.consolidation-table th:first-child { width: 36%; padding-left: 0; }
.consolidation-table th:nth-child(2) { width: 24%; }
.consolidation-table th:nth-child(3) { width: 14%; }
.consolidation-table :is(th,td):last-child { width: 26%; padding-right: 0; text-align: right; }
.consolidation-table thead th { padding-top: 10px; padding-bottom: 10px; color: var(--text-dim); font-size: 10px; font-weight: 500; }
.consolidation-table thead th:nth-child(2), .consolidation-table .consolidation-price { text-align: right; }
.consolidation-table tbody tr { transition: background-color 150ms ease; }
.consolidation-table tbody tr:hover { background: rgba(255,255,255,.025); }
.consolidation-table tbody tr.pending { background: rgba(224,187,132,.025); }
.consolidation-table tbody tr:last-child > * { border-bottom: 0; }
.consolidation-identity strong { font-size: 12px; font-weight: 550; }
.consolidation-identity strong span { display: inline-block; width: 28px; color: var(--text-dim); font-family: var(--font-mono); font-size: 11px; }
.consolidation-dates { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 2px 8px; margin-top: 8px; padding-left: 28px; color: var(--text-muted); font-size: 11px; font-weight: 400; line-height: 1.7; }
.consolidation-dates time:first-child { grid-column: 2; }
.consolidation-dates > span { color: var(--text-dim); }
.consolidation-price { font: 12px var(--font-mono); color: #d8dee8; }
.range-separator { color: var(--text-dim); }
.pen-values { color: var(--text-muted); font: 11px/1.8 var(--font-mono); }
.consolidation-state { text-align: right; }
.consolidation-state strong { display: inline-flex; align-items: center; gap: 6px; color: #b0b6c3; font-size: 11px; font-weight: 400; }
.consolidation-state i { width: 5px; height: 5px; border: 1px solid currentColor; border-radius: 50%; }
.consolidation-state.confirmed strong { color: #a6c2b5; }
.consolidation-state:not(.confirmed) strong { color: #e0bb84; }
.consolidation-state.confirmed i { background: currentColor; }
.consolidation-state small { display: block; margin-top: 6px; color: var(--text-dim); font-size: 10px; line-height: 1.7; }
.mobile-label { display: none; }
@container (max-width: 700px) {
  .consolidation-boundary { display: block; }
  .consolidation-boundary p { margin-top: 5px; }
  .consolidation-table, .consolidation-table tbody { display: block; }
  .consolidation-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .consolidation-table tbody tr { display: grid; grid-template-columns: minmax(0,1fr) minmax(76px,.6fr); gap: 12px; padding: 16px 0; border-top: 1px solid rgba(255,255,255,.055); }
  .consolidation-table.consolidation-table tbody :is(th,td) { width: auto; padding: 0; border: 0; min-width: 0; }
  .consolidation-table .consolidation-identity { grid-column: 1; grid-row: 1; }
  .consolidation-table .consolidation-state { grid-column: 2; grid-row: 1; }
  .consolidation-table .consolidation-price, .consolidation-table .consolidation-pens { grid-column: 1 / -1; display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 6px 12px; padding-left: 28px; }
  .mobile-label { display: inline; color: var(--text-dim); font-family: var(--font-sans, inherit); font-size: 11px; }
  .consolidation-dates { padding-left: 0; }
}
.consolidation-panel { container-type: inline-size; }
@container (max-width: 260px) {
  .consolidation-table tbody tr { grid-template-columns: minmax(0,1fr); }
  .consolidation-table .consolidation-state { grid-column: 1; grid-row: 4; text-align: left; }
  .consolidation-table .consolidation-price, .consolidation-table .consolidation-pens { padding-left: 0; }
  .consolidation-state small { display: inline; margin-left: 8px; }
}
@media (prefers-reduced-motion: reduce) { .consolidation-table tbody tr { transition: none; } }
</style>
