<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import type { ChanlunDivergence, ChanlunSignal, WaveDiagnostic } from '../types'
import { evidenceStateLabels, filterEvidence, indexEvidenceDiagnostics, indexEvidenceEvents, indexStructureSignals, indexMacdPrompts, type EvidenceFilter, type EvidenceState, type EvidenceDateFocus } from '../signal-evidence-index'
import MacSelect from './MacSelect.vue'

const props = defineProps<{ events: ChanlunDivergence[]; signals?: ChanlunSignal[]; diagnostics?: WaveDiagnostic[]; entry?: 'signals' | 'divergence' }>()
const emit = defineEmits<{ returnChart: [date: string] }>()
const root = ref<HTMLElement>()
const filter = reactive<EvidenceFilter>({ family: 'all', state: 'all', direction: 'all', query: '' })
const eventIndex = computed(() => indexEvidenceEvents(props.events))
const diagnosticIndex = computed(() => indexEvidenceDiagnostics(props.diagnostics ?? []))
const signalIndex = computed(() => indexStructureSignals(props.signals ?? []))
const promptIndex = computed(() => indexMacdPrompts(props.events))
const events = computed(() => filterEvidence(eventIndex.value, filter))
const diagnostics = computed(() => filterEvidence(diagnosticIndex.value, filter))
const signals = computed(() => filterEvidence(signalIndex.value, filter))
const prompts = computed(() => filterEvidence(promptIndex.value, filter))
const pageSize = 40
const eventLimit = ref(pageSize)
const diagnosticLimit = ref(pageSize)
const signalLimit = ref(pageSize)
const promptLimit = ref(pageSize)
const view = ref<'events' | 'diagnostics' | 'signals' | 'prompts'>('events')
watch(() => props.entry, entry => { view.value = entry === 'signals' ? 'signals' : props.events.some(item => item.bc) ? 'events' : 'diagnostics' }, { immediate: true })
const active = computed(() => filter.family !== 'all' || filter.state !== 'all' || filter.direction !== 'all' || !!filter.query.trim() || !!filter.date)
watch([filter, eventIndex, diagnosticIndex, signalIndex, promptIndex], () => { eventLimit.value = pageSize; diagnosticLimit.value = pageSize; signalLimit.value = pageSize; promptLimit.value = pageSize })
const families = [
  { value: 'all', label: '全部类型' }, { value: 'standard', label: '标准波段' },
  { value: 'nonstandard', label: '非标准波段' }, { value: 'special', label: '特殊波段' },
  { value: 'double', label: '局部双线' }, { value: 'structure', label: '结构背驰' },
  { value: 'structure_signal', label: '结构性买卖点' }, { value: 'macd_prompt', label: 'MACD M1 提示' },
] as const
const states = [{ value: 'all' as const, label: '全部状态' },
  ...(Object.entries(evidenceStateLabels) as [EvidenceState, string][]).map(([value, label]) => ({ value, label }))]
const directions = [{ value: 'all', label: '全部方向' }, { value: 'down', label: '底部 / 买入' }, { value: 'up', label: '顶部 / 卖出' }] as const
const views = computed(() => [
  { value: 'signals' as const, label: '结构买卖点', count: signals.value.length },
  { value: 'prompts' as const, label: 'MACD M1', count: prompts.value.length },
  { value: 'events' as const, label: '背离事件', count: events.value.length },
  { value: 'diagnostics' as const, label: '规则核验', count: diagnostics.value.length },
])
const currentCount = computed(() => views.value.find(item => item.value === view.value)?.count ?? 0)
const anyMatch = computed(() => views.value.some(item => item.count))
function reset() { Object.assign(filter, { family: 'all', state: 'all', direction: 'all', query: '', date: undefined }) }
async function inspectDate(focus: EvidenceDateFocus) {
  reset(); filter.date = { ...focus }
  view.value = events.value.length ? 'events' : signals.value.length ? 'signals' : 'diagnostics'
  await nextTick()
  root.value?.scrollIntoView({ block: 'start' })
  root.value?.focus({ preventScroll: true })
}
defineExpose({ inspectDate })
</script>

<template>
  <section ref="root" class="evidence-browser" aria-label="信号证据检索" tabindex="-1">
    <header class="evidence-heading"><div><h3>信号证据</h3><p>买卖点、M1、背离与核验共用检索，各自保留独立依据。</p></div><button v-if="active" type="button" class="evidence-reset" @click="reset">清除筛选</button></header>
    <div v-if="filter.date" class="evidence-date-focus" role="status"><div><strong>图表日期 · {{ filter.date.precision === 'day' ? filter.date.date.slice(0, 10) : filter.date.date.replace('T', ' ').slice(0, 16) }}</strong><p>匹配极值、对照、提示、确认、失效日期，以及覆盖该{{ filter.date.precision === 'day' ? '日' : '时刻' }}的 A/B/C 或拦截区间；不代表当时已确认。</p></div><button type="button" @click="emit('returnChart', filter.date.date)">返回图表</button></div>
    <div class="evidence-filters">
      <label class="evidence-search"><span>日期或原因</span><input v-model="filter.query" type="search" placeholder="日期、面积、反向笔…" autocomplete="off" /></label>
      <div><span>识别类型</span><MacSelect v-model="filter.family" :options="families" aria-label="证据识别类型" /></div>
      <div><span>当前状态</span><MacSelect v-model="filter.state" :options="states" aria-label="证据当前状态" /></div>
      <div><span>方向</span><MacSelect v-model="filter.direction" :options="directions" aria-label="证据方向" /></div>
    </div>
    <p class="evidence-count" role="status">买卖点 {{ signals.length }} / {{ signalIndex.length }} 条<span aria-hidden="true">·</span>M1 {{ prompts.length }} / {{ promptIndex.length }} 条<span aria-hidden="true">·</span>背离 {{ events.length }} / {{ eventIndex.length }} 条<span aria-hidden="true">·</span>核验 {{ diagnostics.length }} / {{ diagnosticIndex.length }} 组</p>
    <p class="evidence-scope">仅搜索本次快照返回的日期、依据与拦截记录。M1 是部分已确认标准波段背离的提示，不是结构性一类点；各视图数量不相加作为信号总数。</p>
    <div class="evidence-views" role="group" aria-label="证据视图">
      <button v-for="item in views" :key="item.value" type="button" :aria-pressed="view === item.value" @click="view = item.value">{{ item.label }} <span>{{ item.count }}</span></button>
    </div>
    <div v-if="!anyMatch" class="evidence-empty">
      <strong>{{ active ? '没有匹配的证据' : '本次快照没有返回事件或核验记录' }}</strong>
      <p>{{ active ? '可调整类型、状态或关键词；筛选无结果不代表行情中没有信号。' : '缺少记录不能解释为所有规则均未通过，也不能据此判断不存在信号。' }}</p>
    </div>
    <div v-else-if="!currentCount" class="evidence-empty">
      <strong>当前视图没有{{ active ? '匹配' : '返回' }}记录</strong>
      <p>筛选条件在各视图间保留；可切换到有记录的视图，或调整筛选。不将缺少记录解释为所有条件未通过。</p>
    </div>
    <template v-if="view === 'signals'">
      <slot name="signals" :items="signals.slice(0, signalLimit)" :count="signals.length" />
      <button v-if="signals.length > signalLimit" type="button" class="evidence-more" @click="signalLimit += pageSize">展开更多买卖点（已显示 {{ signalLimit }} / {{ signals.length }}）</button>
    </template>
    <template v-else-if="view === 'prompts'">
      <slot name="prompts" :items="prompts.slice(0, promptLimit)" :count="prompts.length" />
      <button v-if="prompts.length > promptLimit" type="button" class="evidence-more" @click="promptLimit += pageSize">展开更多 M1（已显示 {{ promptLimit }} / {{ prompts.length }}）</button>
    </template>
    <template v-else-if="view === 'diagnostics'">
      <slot name="diagnostics" :items="diagnostics.slice(0, diagnosticLimit)" :count="diagnostics.length" />
      <button v-if="diagnostics.length > diagnosticLimit" type="button" class="evidence-more" @click="diagnosticLimit += pageSize">展开更多核验（已显示 {{ diagnosticLimit }} / {{ diagnostics.length }}）</button>
    </template>
    <template v-else>
      <slot name="events" :items="events.slice(0, eventLimit)" :count="events.length" />
      <button v-if="events.length > eventLimit" type="button" class="evidence-more" @click="eventLimit += pageSize">展开更多事件（已显示 {{ eventLimit }} / {{ events.length }}）</button>
    </template>
    <p v-if="props.diagnostics === undefined" class="evidence-scope">此结果未提供规则核验记录；请重新分析以获取当前版本证据。</p>
    <p v-else-if="filter.family === 'structure'" class="evidence-scope">当前规则核验记录覆盖 MACD 背离；结构背驰仅展示已返回的事件，不推断未生成原因。</p>
    <p v-if="view === 'signals'" class="evidence-scope">结构性买卖点仅展示接口返回记录；当前没有结构点的完整未生成原因，不用 MACD 核验替代结构核验。</p>
    <p v-if="view === 'prompts'" class="evidence-scope">M1 必须满足原提示条件及有效确认时点；未确认和已失效的来源可在背离事件中查询。</p>
  </section>
</template>

<style scoped>
.evidence-browser { min-width: 0; container-type: inline-size; }
.evidence-date-focus { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 0; margin-bottom: 16px; border-block: 1px solid var(--border); }
.evidence-date-focus > div { flex: 1 1 220px; }
.evidence-date-focus strong { font-size: 12px; font-weight: 500; color: var(--text); }
.evidence-date-focus p { margin: 6px 0 0; font-size: 11px; line-height: 1.8; color: var(--text-dim); }
.evidence-date-focus button { font-size: 11px; min-height: 34px; }
.evidence-browser { scroll-margin-top: 90px; }
.evidence-browser:focus-visible { outline: 2px solid var(--accent); outline-offset: 5px; }
.evidence-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; padding: 6px 0 16px; }
.evidence-heading h3 { margin: 0; font-size: 15px; font-weight: 550; color: var(--text); }
.evidence-heading p, .evidence-scope, .evidence-empty p { margin: 7px 0 0; font-size: 11px; line-height: 1.8; color: var(--text-muted); overflow-wrap: anywhere; }
.evidence-filters { display: grid; grid-template-columns: minmax(180px, 1.7fr) minmax(110px, 1fr) minmax(150px, 1.2fr) minmax(88px, .7fr); gap: 12px; }
.evidence-filters > * { min-width: 0; }
.evidence-filters span { display: block; margin-bottom: 6px; font-size: 10px; color: var(--text-muted); }
.evidence-search input { width: 100%; box-sizing: border-box; min-width: 0; height: 36px; padding: 0 10px; color: var(--text); background: var(--bg-input, #15171c); border: 1px solid var(--border, #343842); border-radius: 8px; font-size: 12px; }
.evidence-filters :deep(.mac-select-trigger) { height: 36px; min-height: 36px; }
.evidence-search input:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.evidence-count { display: flex; flex-wrap: wrap; gap: 8px; color: var(--text-dim); font-size: 11px; font-variant-numeric: tabular-nums; margin: 14px 0 0; }
.evidence-scope { margin-bottom: 18px; }
.evidence-views { display: flex; flex-wrap: wrap; gap: 4px 24px; border-bottom: 1px solid var(--border); margin-bottom: 18px; }
.evidence-views button { display: inline-flex; align-items: center; gap: 8px; min-height: 40px; padding: 8px 0; border: 0; border-radius: 0; border-bottom: 2px solid transparent; background: transparent; box-shadow: none; color: var(--text-muted); font-size: 12px; cursor: pointer; }
.evidence-views button[aria-pressed="true"] { color: var(--text); border-bottom-color: var(--accent); }
.evidence-views span { font-size: 10px; font-variant-numeric: tabular-nums; color: var(--text-muted); }
.evidence-reset, .evidence-more { background: transparent; border: 0; box-shadow: none; color: var(--accent-hover, #92b9e8); min-height: 36px; padding: 6px 0; cursor: pointer; font-size: 11px; }
.evidence-reset { flex-shrink: 0; }
.evidence-more { display: block; width: 100%; text-align: center; margin: 8px 0 18px; border-bottom: 1px solid var(--border); }
.evidence-empty { padding: 22px 0; border-block: 1px solid var(--border); }
.evidence-empty strong { color: var(--text-dim); font-size: 12px; font-weight: 500; }
@container (max-width: 740px) { .evidence-filters { grid-template-columns: repeat(2, minmax(0, 1fr)); } .evidence-search { grid-column: 1 / -1; } }
@container (max-width: 360px) { .evidence-heading { align-items: flex-start; } .evidence-filters { gap: 10px; } }
@container (max-width: 250px) { .evidence-filters { grid-template-columns: minmax(0, 1fr); } }
</style>
