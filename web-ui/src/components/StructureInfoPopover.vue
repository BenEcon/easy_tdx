<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ChanlunResult, ChanlunDivergence } from '../types'
import { structureDate } from '../structure-display'
import { boundedPopover } from '../consolidation-hit'
import { divergenceName, divergenceEvidence } from '../divergence-evidence'
import EvidenceReading from './EvidenceReading.vue'

type Area = NonNullable<ChanlunResult['pen_consolidations']>[number]
const panel = ref<HTMLElement>()
const choices = ref<Array<{ index: number; area: Area }>>([])
const divergences = ref<ChanlunDivergence[]>([])
const selected = ref(0)
const current = computed(() => choices.value[selected.value])
const divergence = computed(() => divergences.value[selected.value])
const status = (item: ChanlunDivergence) => item.status === 'superseded' ? '已失效／被替代' : item.status === 'confirmed' ? '已确认' : '候选 · 尚未确认'
const evidenceOpen = ref(false)
const position = ref({ left: 12, top: 12 })
let revision = 0
let returnFocus: HTMLElement | null = null
let anchor = { x: 0, y: 0 }
async function place() {
  await nextTick()
  if (!panel.value?.matches(':popover-open')) return
  const rect = panel.value.getBoundingClientRect()
  position.value = boundedPopover(anchor.x, anchor.y, rect.width, rect.height, window.innerWidth, window.innerHeight)
}
async function show(items: Array<{ index: number; area: Area }>, x: number, y: number) {
  if (!items.length) return
  choices.value = items
  divergences.value = []
  await open(x, y)
}
async function showDivergences(items: ChanlunDivergence[], x: number, y: number) {
  if (!items.length) return
  divergences.value = items
  choices.value = []
  await open(x, y)
}
async function open(x: number, y: number) {
  const version = ++revision
  if (!panel.value?.matches(':popover-open')) returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  selected.value = 0
  evidenceOpen.value = false
  anchor = { x, y }
  await nextTick()
  if (version !== revision || !panel.value) return
  panel.value.showPopover()
  await place()
  panel.value.querySelector<HTMLButtonElement>('.popover-close')?.focus({ preventScroll: true })
}
function hide(restoreFocus = true) {
  revision++
  if (panel.value?.matches(':popover-open')) {
    const hadFocus = panel.value.contains(document.activeElement)
    panel.value.hidePopover()
    if (restoreFocus && hadFocus && returnFocus?.isConnected) returnFocus.focus({ preventScroll: true })
  }
}
function choose(index: number) { selected.value = index; evidenceOpen.value = false; void place() }
function toggleEvidence() { evidenceOpen.value = !evidenceOpen.value; void place() }
function outside(event: Event) { if (panel.value?.matches(':popover-open') && !event.composedPath().includes(panel.value)) hide(false) }
function escape(event: KeyboardEvent) {
  if (event.key === 'Escape' && panel.value?.matches(':popover-open')) { event.preventDefault(); event.stopImmediatePropagation(); hide() }
}
onMounted(() => { document.addEventListener('pointerdown', outside, true); document.addEventListener('keydown', escape, true) })
onBeforeUnmount(() => { hide(false); document.removeEventListener('pointerdown', outside, true); document.removeEventListener('keydown', escape, true) })
defineExpose({ show, showDivergences, hide })
</script>

<template>
  <section ref="panel" popover="manual" role="dialog" :aria-label="divergence ? '背离／背驰详情' : '盘整区间详情'" class="consolidation-popover" :style="{ left: `${position.left}px`, top: `${position.top}px` }">
    <template v-if="divergence">
      <header><div><strong>{{ divergenceName(divergence) }}</strong><span :class="{ ongoing: divergence.status === 'candidate', inactive: divergence.status === 'superseded' }">{{ status(divergence) }}</span></div><button type="button" class="popover-close" aria-label="关闭背离详情" @click="hide()">×</button></header>
      <nav v-if="divergences.length > 1" aria-label="切换背离标记"><button v-for="(item, index) in divergences" :key="index" type="button" :aria-pressed="selected === index" @click="choose(index)">{{ divergenceName(item) }} · {{ structureDate(item.curr_date) }} · {{ status(item) }}</button></nav>
      <dl>
        <div><dt>极值时间</dt><dd>{{ structureDate(divergence.curr_date) }}</dd></div>
        <div><dt>对照时间</dt><dd>{{ structureDate(divergence.prev_date) }}</dd></div>
        <div><dt>首次提示</dt><dd>{{ structureDate(divergence.detected_date) }}</dd></div>
        <div v-if="divergence.preliminary_date"><dt>初步确认</dt><dd>{{ structureDate(divergence.preliminary_date) }}</dd></div>
        <div v-if="divergence.status === 'confirmed'"><dt>实际确认</dt><dd>{{ structureDate(divergence.confirmed_date) }}</dd></div>
        <div v-if="divergence.status === 'superseded'"><dt>失效时间</dt><dd>{{ structureDate(divergence.invalidated_date) }}</dd></div>
      </dl>
      <p class="signal-message">{{ divergence.msg }}</p>
      <p v-if="divergence.failure_reason" class="live-note">失效原因：{{ divergence.failure_reason }}</p>
      <button type="button" class="evidence-toggle" :aria-expanded="evidenceOpen" @click="toggleEvidence">{{ evidenceOpen ? '收起判定依据' : '查看判定依据' }}<span aria-hidden="true">{{ evidenceOpen ? '−' : '＋' }}</span></button>
      <EvidenceReading v-if="evidenceOpen" :lines="divergenceEvidence(divergence)" />
      <footer>极值时间与实际确认时间分别记录；确认不保证价格反转。</footer>
    </template>
    <template v-if="current">
      <header><div><strong>盘整 {{ current.index + 1 }}</strong><span :class="{ ongoing: !current.area.confirmed }">{{ current.area.confirmed ? '三笔已确认' : '进行中 · 末笔待确认' }}</span></div><button type="button" class="popover-close" aria-label="关闭盘整详情" @click="hide()">×</button></header>
      <nav v-if="choices.length > 1" aria-label="切换盘整区间"><button v-for="(item, index) in choices" :key="item.index" type="button" :aria-pressed="selected === index" @click="choose(index)">盘整 {{ item.index + 1 }}</button></nav>
      <dl>
        <div><dt>重叠价格</dt><dd>{{ current.area.lower.toFixed(2) }} — {{ current.area.upper.toFixed(2) }}</dd></div>
        <div><dt>开始时间</dt><dd>{{ structureDate(current.area.start_date) }}</dd></div>
        <div><dt>结束端点</dt><dd>{{ structureDate(current.area.end_date) }}</dd></div>
        <div><dt>来源笔</dt><dd>{{ current.area.pen_indices.map(index => index + 1).join('、') }}</dd></div>
      </dl>
      <p v-if="!current.area.confirmed" class="live-note">末笔尚未确认，重叠范围与端点仍可变化。</p>
      <footer>三笔价格重叠，不等同于中枢，不作为独立交易依据。</footer>
    </template>
  </section>
</template>

<style scoped>
.consolidation-popover { position: fixed; inset: auto; margin: 0; width: min(340px, calc(100vw - 24px)); box-sizing: border-box; max-height: calc(100dvh - 24px); overflow: auto; padding: 18px; border: 1px solid rgba(177,196,221,.2); border-radius: 12px; color: #cad3df; background: #202228; box-shadow: 0 14px 45px rgba(0,0,0,.38); font: 12px var(--font-mono); }
.consolidation-popover::backdrop { background: transparent; }
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
header strong { display: block; color: #edf1f7; font-size: 14px; font-weight: 600; }
header span { display: block; color: #a7c6b7; font-size: 10px; margin-top: 6px; }
header span.ongoing { color: #e0bb84; }
.popover-close { min-width: 28px; min-height: 28px; padding: 0; font-size: 20px; line-height: 1; color: #aab5c5; background: transparent; border: 0; box-shadow: none; }
nav { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 16px; max-height: 120px; overflow: auto; }
nav button { min-height: 30px; padding: 4px 8px; font-size: 10px; border: 1px solid transparent; background: rgba(255,255,255,.03); color: #9facbf; box-shadow: none; border-radius: 5px; }
nav button[aria-pressed="true"] { color: #cce0f6; background: rgba(122,169,220,.12); border-color: rgba(122,169,220,.2); }
button { cursor: pointer; }
button:focus-visible { outline: 2px solid #83acd5; outline-offset: 2px; }
dl { margin: 16px 0 10px; }
dl > div { display: grid; grid-template-columns: 64px minmax(0,1fr); gap: 14px; padding: 9px 0; border-top: 1px solid rgba(255,255,255,.05); line-height: 1.7; }
dt { color: #929fb0; font-size: 10px; }
dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
footer, .live-note { margin: 10px 0 0; font-size: 10px; line-height: 1.8; color: #96a3b6; }
.live-note { color: #cbb38b; }
header span.inactive { color: #99a1ad; }
.signal-message { margin: 10px 0; font-size: 11px; line-height: 1.9; overflow-wrap: anywhere; text-align: justify; }
.evidence-toggle { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 10px 0; border: 0; border-top: 1px solid rgba(255,255,255,.08); border-radius: 0; background: transparent; color: #b3c9e1; font-size: 11px; box-shadow: none; }
</style>
