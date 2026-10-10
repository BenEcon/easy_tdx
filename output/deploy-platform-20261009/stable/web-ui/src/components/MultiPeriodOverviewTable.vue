<script setup lang="ts">
import { computed } from 'vue'
import { periodOverviewCells, overviewColumns } from '../period-overview'
import { studyLabel, type StudyRow, type StudyPeriod } from '../research-study'

const props = defineProps<{ periods: readonly StudyPeriod[]; rows: StudyRow[]; errors: Record<string, string>; loading: boolean }>()
const emit = defineEmits<{ inspect: [period: StudyPeriod] }>()
const records = computed(() => props.periods.map(category => {
  const row = props.rows.find(item => item.category === category)
  const error = props.errors[category] || row?.error
  return { category, row, error, cells: row && !error ? periodOverviewCells(row) : null }
}))
function scrollColumns(event: KeyboardEvent) {
  // Only handle the scroll region itself; buttons and disclosures retain their keys.
  if (event.target !== event.currentTarget || event.altKey || event.ctrlKey || event.metaKey) return
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  const region = event.currentTarget as HTMLElement
  event.preventDefault()
  region.scrollBy({ left: event.key === 'ArrowRight' ? 180 : -180, behavior: 'instant' })
}
</script>

<template>
  <section class="period-overview" aria-label="多周期概览表" :aria-busy="loading">
    <p class="overview-help">横向查看各项信息；点击周期查看完整依据。成交量均线沿用行情原始口径，同周期比较；数值显示两位小数，判定使用未舍入值。</p>
    <div class="overview-scroll" tabindex="0" role="region" aria-label="多周期概览数据，可横向滚动" @keydown="scrollColumns">
      <table>
        <caption class="sr-only">所选标的按周期汇总的量价、动能、严格笔与背离信息</caption>
        <thead><tr><th scope="col">周期</th><th v-for="column in overviewColumns" :key="column" scope="col">{{ column }}</th></tr></thead>
        <tbody>
          <tr v-for="record in records" :key="record.category">
            <th scope="row"><button v-if="record.cells" type="button" @click="emit('inspect', record.category)" :aria-label="`查看${studyLabel(record.category)}完整依据`">{{ studyLabel(record.category) }} <span aria-hidden="true">↗</span></button><strong v-else>{{ studyLabel(record.category) }}</strong><small v-if="record.row?.last_closed_at">已收盘截止<time>{{ record.row.last_closed_at }}</time></small></th>
            <td v-if="record.error" colspan="6" class="overview-error">{{ record.error }}<small>本周期未得出结论；其他周期独立保留。</small></td>
            <template v-else-if="record.cells">
              <td v-for="(cell, index) in record.cells" :key="index"><p v-for="(line, i) in cell.slice(0, 4)" :key="i">{{ line }}</p><details v-if="cell.length > 4"><summary>其余 {{ cell.length - 4 }} 条</summary><p v-for="(line, i) in cell.slice(4)" :key="i">{{ line }}</p></details></td>
            </template>
            <td v-else colspan="6" class="overview-pending">{{ loading ? '正在按共同截止时间核验…' : '等待更新研究' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.period-overview { min-width: 0; margin: 16px 0 24px; }
.overview-help { font-size: 11px; line-height: 1.8; color: var(--text-muted); margin: 0 0 10px; }
.overview-scroll { max-width: 100%; max-height: 680px; overflow: auto; border: 1px solid var(--border); border-radius: 10px; scrollbar-gutter: stable; }
.overview-scroll:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
table { width: 100%; min-width: 1280px; border-collapse: separate; border-spacing: 0; font-size: 11px; line-height: 1.8; }
th, td { padding: 14px 16px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
thead th { position: sticky; top: 0; z-index: 2; background: var(--bg-panel, #1c1e23); color: var(--text-dim); font-size: 11px; font-weight: 500; white-space: nowrap; }
tbody th { position: sticky; left: 0; z-index: 1; background: var(--bg-panel, #1c1e23); width: 126px; min-width: 126px; box-shadow: 1px 0 0 var(--border); }
thead th:first-child { left: 0; z-index: 3; }
tbody td { min-width: 160px; max-width: 270px; overflow-wrap: anywhere; }
tbody td:nth-child(5), tbody td:nth-child(6) { min-width: 210px; }
tbody tr:last-child > * { border-bottom: 0; }
tbody tr:hover td { background: rgba(120,160,210,.025); }
td p { margin: 0 0 7px; color: #aeb9c8; } td p:last-child { margin-bottom: 0; } td p:first-child { color: var(--text); }
th button { padding: 0; min-height: 32px; border: 0; background: transparent; box-shadow: none; color: var(--accent-hover, #a4c8ee); font: inherit; font-size: 12px; cursor: pointer; white-space: nowrap; }
th strong { font-size: 12px; font-weight: 500; }
th button span { margin-left: 5px; color: var(--text-muted); }
small { display: block; color: var(--text-muted); font-size: 10px; line-height: 1.8; font-weight: 400; margin-top: 6px; }
time { display: block; overflow-wrap: anywhere; }
td.overview-error { color: #e6af81; } td.overview-pending { color: var(--text-muted); padding-block: 28px; }
details summary { color: var(--accent-hover, #a4c8ee); cursor: pointer; margin-top: 8px; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
@media (max-width: 600px) { th, td { padding: 12px; } tbody th { width: 94px; min-width: 94px; } .overview-scroll { max-height: 580px; } }
</style>
