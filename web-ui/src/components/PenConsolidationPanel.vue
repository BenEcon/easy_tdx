<script setup lang="ts">
import { structureDate } from '../structure-display'
defineProps<{
  areas: Array<{ pen_indices: number[]; start_date: string; end_date: string; lower: number; upper: number; confirmed: boolean }>
}>()
</script>

<template>
  <details class="research-panel consolidation-panel">
    <summary>
      <strong>三笔盘整 <small>{{ areas.length }} 组</small></strong>
      <span>笔级重叠 · 非中枢</span>
    </summary>
    <div class="research-panel-body">
      <div class="consolidation-boundary">
        <strong>不等同于中枢</strong>
        <p>这里展示三笔的价格重叠区间，与基础中枢分开识别，不作为独立交易依据。</p>
      </div>
      <div class="consolidation-head" aria-hidden="true"><span>区间 / 时间</span><span>重叠价格</span><span>来源笔</span><span>确认状态</span></div>
      <ol class="consolidation-list">
        <li v-for="(area, index) in areas" :key="area.pen_indices.join('-')">
          <div class="consolidation-identity"><strong><span>{{ String(index + 1).padStart(2, '0') }}</span>盘整区间</strong><small>{{ structureDate(area.start_date) }} → {{ structureDate(area.end_date) }}</small></div>
          <div class="consolidation-price"><span class="mobile-label">重叠价格</span>{{ area.lower.toFixed(2) }} <span class="range-separator">—</span> {{ area.upper.toFixed(2) }}</div>
          <div class="consolidation-pens"><span class="mobile-label">来源笔</span><span v-for="pen in area.pen_indices" :key="pen">{{ pen + 1 }}</span></div>
          <div class="consolidation-state" :class="{ confirmed: area.confirmed }"><strong><i aria-hidden="true"></i>{{ area.confirmed ? '三笔已确认' : '进行中 · 末笔待确认' }}</strong><small v-if="!area.confirmed">区间仍可变化</small></div>
        </li>
      </ol>
    </div>
  </details>
</template>

<style scoped>
.consolidation-panel > summary strong small { margin-left: 8px; color: var(--text-dim); font-size: 11px; font-weight: 400; }
.consolidation-boundary { display: flex; align-items: baseline; gap: 12px; margin: 8px 0 22px; padding-left: 12px; border-left: 2px solid #747f92; }
.consolidation-boundary strong { flex-shrink: 0; font-size: 12px; font-weight: 550; color: #c1cad7; }
.consolidation-boundary p { margin: 0; color: var(--text-muted); font-size: 12px; line-height: 1.8; }
.consolidation-head, .consolidation-list li { display: grid; grid-template-columns: minmax(190px, 1.7fr) minmax(120px, 1fr) minmax(90px, .8fr) minmax(100px, .9fr); gap: 16px; align-items: center; }
.consolidation-head { padding: 0 0 10px; color: var(--text-dim); font-size: 11px; border-bottom: 1px solid var(--border); }
.consolidation-head > :last-child { text-align: right; }
.consolidation-list { list-style: none; padding: 0; margin: 0; }
.consolidation-list li { padding: 17px 0; border-bottom: 1px solid rgba(255,255,255,.05); font-variant-numeric: tabular-nums; }
.consolidation-list li:last-child { border-bottom: 0; padding-bottom: 2px; }
.consolidation-identity strong { font-size: 12px; font-weight: 550; }
.consolidation-identity strong span { display: inline-block; width: 28px; color: var(--text-dim); font-family: var(--font-mono); font-size: 11px; }
.consolidation-identity small { display: block; margin-top: 6px; color: var(--text-muted); font-size: 11px; line-height: 1.7; overflow-wrap: anywhere; }
.consolidation-price { font: 12px var(--font-mono); color: #d8dee8; }
.range-separator { color: var(--text-dim); }
.consolidation-pens { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.consolidation-pens > span:not(.mobile-label) { min-width: 24px; padding: 3px 5px; border-radius: 4px; text-align: center; background: rgba(255,255,255,.035); color: var(--text-muted); font: 11px var(--font-mono); }
.consolidation-state { text-align: right; }
.consolidation-state strong { display: inline-flex; align-items: center; gap: 6px; color: #b0b6c3; font-size: 11px; font-weight: 400; }
.consolidation-state i { width: 5px; height: 5px; border: 1px solid currentColor; border-radius: 50%; }
.consolidation-state.confirmed strong { color: #a6c2b5; }
.consolidation-state:not(.confirmed) strong { color: #e0bb84; }
.consolidation-state.confirmed i { background: currentColor; }
.consolidation-state small { display: block; margin-top: 5px; color: var(--text-dim); font-size: 11px; }
.mobile-label { display: none; }
@container (max-width: 700px) {
  .consolidation-boundary { display: block; }
  .consolidation-boundary p { margin-top: 5px; }
  .consolidation-head { display: none; }
  .consolidation-list li { grid-template-columns: minmax(0, 1fr) auto; gap: 12px; }
  .consolidation-identity { grid-column: 1; grid-row: 1; }
  .consolidation-state { grid-column: 2; grid-row: 1; }
  .consolidation-price, .consolidation-pens { grid-column: 1 / -1; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
  .mobile-label { display: inline; margin-right: 4px; color: var(--text-dim); font-family: inherit; font-size: 11px; }
}
.consolidation-panel { container-type: inline-size; }
</style>
