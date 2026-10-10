<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { Bar, ChanlunResult } from '../types'
import { divergenceName, divergenceEvidence, waveDiagnosticLines, waveFailureSummary } from '../divergence-evidence'
import { segmentEvidence, centreEvidence } from '../structure-evidence'
import { signalName, structuralSignalDetail } from '../chart-signal-detail'
import { structureDate } from '../structure-display'
import { stamp, type TimeWindow } from '../chart-research-link'
import EvidenceReading from './EvidenceReading.vue'
import MacSelect from './MacSelect.vue'

const props = defineProps<{ result: ChanlunResult; bars: Bar[]; title: string; visibleRange?: TimeWindow | null }>()
const emit = defineEmits<{ locate: [date: string] }>()
const root = ref<HTMLDetailsElement>()
const section = ref('signals'), direction = ref('all'), state = ref('all'), kind = ref('all')
const from = ref(''), through = ref(''), visibleOnly = ref(false), selectedDate = ref(''), failureGate = ref('')
const sections = [{ value: 'signals', label: '背离与买卖点' }, { value: 'bis', label: '笔' }, { value: 'xds', label: '线段' }, { value: 'areas', label: '三笔盘整' }, { value: 'centres', label: '中枢' }, { value: 'failures', label: '拦截原因' }]
type Row = { key: string; title: string; date: string; end?: string; state: string; direction?: string; kind: string; message: string; evidence: string[]; raw: unknown }
const rows = computed<Row[]>(() => {
  const r = props.result
  if (section.value === 'bis') return r.bis.map((item, i) => ({ key: `bi${i}`, title: `笔 ${i + 1}`, date: item.start_date, end: item.end_date,
    state: item.done ? 'confirmed' : 'candidate', direction: item.direction, kind: '笔', message: `${item.low.toFixed(2)} — ${item.high.toFixed(2)}`,
    evidence: [`起点：${item.start_date}`, `端点：${item.end_date}`, `实际确认：${item.confirmed_date ?? '未提供'}`, `严格成笔：${item.structurally_confirmed ? '已确认' : '未提供或待确认'}`], raw: item }))
  if (section.value === 'xds') return [...r.xds, ...(r.unfinished_xd ? [r.unfinished_xd] : [])].map((item, i) => ({ key: `xd${i}`, title: `线段 ${i + 1}`, date: item.start_date, end: item.end_date,
    state: item.confirmed_date ? 'confirmed' : 'candidate', direction: item.direction, kind: '线段', message: `${item.low.toFixed(2)} — ${item.high.toFixed(2)}`, evidence: segmentEvidence(item), raw: item }))
  if (section.value === 'areas') return (r.pen_consolidations ?? []).map((item, i) => ({ key: `area${i}`, title: `三笔盘整 ${i + 1}`, date: item.start_date, end: item.end_date,
    state: item.confirmed ? 'confirmed' : 'candidate', kind: '三笔盘整', message: `${item.lower.toFixed(2)} — ${item.upper.toFixed(2)} · 不等同于中枢`, evidence: [`来源笔：${item.pen_indices.map(i => i + 1).join('、')}`], raw: item }))
  if (section.value === 'centres') return (r.structural_centres ?? r.zss).map((item, i) => ({ key: `zs${i}`, title: `中枢 ${i + 1}`, date: item.start_date ?? '', end: item.end_date ?? '',
    state: item.done ? 'confirmed' : 'candidate', kind: '中枢', message: `${item.zd.toFixed(2)} — ${item.zg.toFixed(2)}`, evidence: centreEvidence(item), raw: item }))
  if (section.value === 'failures') return (r.wave_diagnostics ?? []).flatMap((item, i) => {
    const failed = item.checks.filter(check => !check.passed)
    if (!failed.length || (failureGate.value && !failed.some(check => check.gate === failureGate.value))) return []
    const dates = Object.values(item.dates).filter(Boolean).sort()
    return [{ key: `failure${i}`, title: `核验组 ${i + 1}`, date: dates.at(-1) ?? '', state: 'blocked', direction: item.direction,
      kind: item.family ?? 'standard', message: waveFailureSummary(item), evidence: waveDiagnosticLines(item), raw: item }]
  })
  return [
    ...r.bcs.map((item, i) => ({ key: `bc${i}`, title: divergenceName(item), date: item.curr_date ?? '', state: item.status ?? (item.bc ? 'unknown' : 'blocked'), direction: item.direction,
      kind: item.type, message: item.msg, evidence: divergenceEvidence(item), raw: item })),
    ...r.mmds.map((item, i) => ({ key: `signal${i}`, title: signalName(item.type), date: item.date ?? '', state: item.confirmed_date ? 'confirmed' : 'unknown', direction: item.type.includes('buy') ? 'down' : 'up',
      kind: 'structural', message: item.msg, evidence: structuralSignalDetail(item, 0).evidence, raw: item })),
  ]
})
const kinds = computed(() => [{ value: 'all', label: '全部类型' }, ...[...new Set(rows.value.map(row => row.kind))].map(value => ({ value, label: ({ bi: '笔背离', pz: '盘整背驰', qs: '趋势背驰', macd: '双线背离', macd_wave: '标准波段背离', macd_wave_nonstandard: '非标准波段背离', macd_wave_special: '特殊波段背离', structural: '结构性买卖点' } as Record<string,string>)[value] ?? value }))])
const filtered = computed(() => rows.value.filter(row => (!selectedDate.value || stamp(row.date) === stamp(selectedDate.value))
  && (direction.value === 'all' || row.direction === direction.value) && (state.value === 'all' || row.state === state.value)
  && (kind.value === 'all' || row.kind === kind.value) && (!from.value || row.date.slice(0, 10) >= from.value) && (!through.value || row.date.slice(0, 10) <= through.value)
  && (!visibleOnly.value || (props.visibleRange && stamp(row.end ?? row.date) >= props.visibleRange.start && stamp(row.date) <= props.visibleRange.end))))
const pageSize = ref(30)
const shown = computed(() => filtered.value.slice(0, pageSize.value))
const gates = computed(() => {
  const map = new Map<string, { label: string; count: number }>()
  for (const item of props.result.wave_diagnostics ?? []) for (const check of item.checks.filter(check => !check.passed)) {
    const entry = map.get(check.gate)
    map.set(check.gate, { label: waveFailureSummary({ checks: [check] }), count: (entry?.count ?? 0) + 1 })
  }
  return [...map].map(([value, entry]) => ({ value, label: `${entry.label} · ${entry.count} 组` }))
})
watch([section, direction, state, kind, from, through, visibleOnly, selectedDate, failureGate], () => { pageSize.value = 30 })
watch(section, () => { kind.value = 'all'; selectedDate.value = ''; state.value = 'all'; direction.value = 'all' })
watch(() => props.result, () => { selectedDate.value = ''; failureGate.value = ''; pageSize.value = 30 })
async function inspect(date: string) {
  const hasSignal = props.result.bcs.some(item => item.curr_date === date) || props.result.mmds.some(item => item.date === date)
  section.value = !hasSignal && props.result.pen_consolidations?.some(item => item.start_date === date) ? 'areas' : 'signals'; await nextTick()
  kind.value = 'all'; state.value = 'all'; direction.value = 'all'; from.value = ''; through.value = ''; visibleOnly.value = false; selectedDate.value = date
  if (root.value) { root.value.open = true; root.value.scrollIntoView({ block: 'start', behavior: 'smooth' }); root.value.querySelector('summary')?.focus() }
}
defineExpose({ inspect })
const statusLabel = (value: string) => ({ confirmed: '已确认', candidate: '进行中／候选', superseded: '已失效／被替代', blocked: '未通过', unknown: '确认时间未提供' }[value] ?? value)
</script>
<template>
  <details ref="root" class="period-inspector research-panel research-hierarchy">
    <summary><strong>周期明细审核</strong><span>{{ title }} · {{ bars.length }} 根</span></summary>
    <div class="research-content">
      <div class="research-controls">
        <MacSelect v-model="section" :options="sections" aria-label="审核结构类型" />
        <MacSelect v-model="state" :options="[{ value: 'all', label: '全部状态' }, ...['confirmed', 'candidate', 'superseded', 'blocked', 'unknown'].map(value => ({ value, label: statusLabel(value) }))]" aria-label="筛选状态" />
        <MacSelect v-model="direction" :options="[{ value: 'all', label: '全部方向' }, { value: 'up', label: '向上／顶部' }, { value: 'down', label: '向下／底部' }]" aria-label="筛选方向" />
        <MacSelect v-if="section === 'signals'" v-model="kind" :options="kinds" aria-label="筛选信号类型" />
        <label>起始<input v-model="from" type="date" aria-label="起始日期" /></label><label>截止<input v-model="through" type="date" aria-label="截止日期" /></label>
        <label><input v-model="visibleOnly" type="checkbox" :disabled="!visibleRange" />仅图中可见范围</label>
      </div>
      <div v-if="section === 'failures'" class="failure-tools"><MacSelect v-model="failureGate" :options="[{ value: '', label: '全部拦截条件' }, ...gates]" aria-label="拦截原因分组" /><p>统计当前快照已返回的核验组；一组可有多项失败。不代表强弱评分，也不宣称覆盖尚未计算的候选。</p></div>
      <p class="research-count">{{ filtered.length }} 条<span v-if="selectedDate"> · 定位 {{ structureDate(selectedDate) }} <button @click="selectedDate = ''">清除日期定位</button></span></p>
      <p v-if="!filtered.length" role="status">当前条件下没有记录。可清除筛选或切换结构类型。</p>
      <article v-for="row in shown" :key="row.key" class="research-record">
        <header><div><strong>{{ row.title }}</strong><span>{{ statusLabel(row.state) }}</span></div><button v-if="row.date" @click="emit('locate', row.date)">图中定位</button></header>
        <p class="research-date">{{ structureDate(row.date) }}<template v-if="row.end"> — {{ structureDate(row.end) }}</template></p>
        <p>{{ row.message }}</p>
        <details><summary>依据与原始记录</summary><EvidenceReading :lines="row.evidence" /><details><summary>原始记录</summary><pre>{{ JSON.stringify(row.raw, null, 2) }}</pre></details></details>
      </article>
      <button v-if="shown.length < filtered.length" @click="pageSize += 30">再显示 30 条</button>
    </div>
  </details>
</template>
<style scoped>
.period-inspector { margin-top: 18px; min-width: 0; }
.research-content { padding: 14px 0 10px 20px; }
.research-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.research-controls :deep(.mac-select) { width: 155px; max-width: 100%; }
.research-controls label { display: flex; align-items: center; gap: 7px; color: var(--text-muted); font-size: 11px; }
.research-controls input[type=checkbox] { width: 14px; height: 14px; min-height: 14px; padding: 0; margin: 0; flex: 0 0 14px; accent-color: #85b5e8; }
.research-controls input[type=date] { width: 135px; padding: 5px; color: var(--text); background: var(--bg-deep); border: 1px solid var(--border); border-radius: 6px; }
.failure-tools { margin-top: 12px; max-width: 100%; }
.failure-tools :deep(.mac-select) { max-width: 100%; width: 440px; }
.research-record { padding: 16px 0; border-top: 1px solid var(--border); }
.research-record header, .research-record header > div { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; }
.research-record header { justify-content: space-between; }
.research-record strong { font-size: 12px; color: var(--text); }
.research-record header span, .research-date, .research-count { font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
p { font-size: 12px; line-height: 1.85; color: var(--text-muted); overflow-wrap: anywhere; }
.research-record p { text-align: justify; }
button { min-height: 30px; padding: 4px 9px; color: var(--text-muted); background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 6px; font-size: 11px; cursor: pointer; }
button:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.research-record summary { cursor: pointer; color: var(--text-muted); padding-block: 8px; font-size: 11px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; line-height: 1.8; }
@media(max-width:600px) { .research-content { padding-left: 8px; } .research-controls :deep(.mac-select) { width: calc(50% - 5px); } }
</style>
