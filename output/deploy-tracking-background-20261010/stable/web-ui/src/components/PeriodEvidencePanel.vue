<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { replayChanlun, formatError } from '../api'
import type { ChanlunDivergence, ChanlunResult } from '../types'
import { chartBarIndex } from '../chart-position'
import { periodLabel } from '../period-comparison'
import { evidenceReplayRequest, type EvidenceSource } from '../evidence-replay'
import SignalEvidenceWorkspace from './SignalEvidenceWorkspace.vue'

const props = defineProps<{ source: EvidenceSource; title: string; busy: boolean }>()
const emit = defineEmits<{ locate: [date: string]; locateDivergence: [item: ChanlunDivergence, reverse: boolean] }>()
const root = ref<HTMLDetailsElement>()
const opened = ref(false)
const workspace = ref<InstanceType<typeof SignalEvidenceWorkspace>>()
const replay = shallowRef<{ result: ChanlunResult; position: number } | null>(null)
const loading = ref(false), error = ref(''), context = ref(0)
let generation = 0, controller: AbortController | null = null
const currentBars = computed(() => props.source.bars.slice(0, replay.value?.position ?? props.source.bars.length))
const currentResult = computed(() => replay.value?.result ?? props.source.result)
const cutoff = computed(() => currentBars.value.at(-1)?.period_end ?? currentBars.value.at(-1)?.datetime ?? '无行情')
function restore() {
  generation++; controller?.abort(); controller = null
  replay.value = null; loading.value = false; error.value = ''; context.value++
}
watch([() => props.source.category, () => props.source.bars, () => props.source.result], restore, { flush: 'sync' })
watch(() => props.busy, value => { if (value) restore() })
onBeforeUnmount(restore)
async function seek(position: number) {
  if (props.busy || loading.value) return
  let request: ReturnType<typeof evidenceReplayRequest>
  try { request = evidenceReplayRequest(props.source, position) } catch (err) { error.value = formatError(err); return }
  if (position === props.source.bars.length) { restore(); return }
  controller?.abort(); controller = new AbortController()
  const signal = controller.signal, version = ++generation
  loading.value = true; error.value = ''
  try {
    const result = await replayChanlun(request, signal)
    if (version !== generation) return
    replay.value = { result, position }
  } catch (err) { if (version === generation) error.value = formatError(err) }
  finally { if (version === generation) loading.value = false }
}
async function inspect(date: string) {
  const index = chartBarIndex(props.source.bars, date)
  if (index === null) return
  restore(); opened.value = true
  if (root.value) root.value.open = true
  await nextTick()
  await workspace.value?.inspectDate({ date: props.source.bars[index]!.datetime, precision: props.source.category.startsWith('MIN_') ? 'minute' : 'day' })
}
defineExpose({ inspect })
</script>

<template>
  <details ref="root" class="period-evidence research-panel research-hierarchy" @toggle="opened = !!root?.open">
    <summary><strong>周期信号证据</strong><span>{{ title }} · {{ periodLabel(source.category) }}</span></summary>
    <div v-if="opened" class="research-panel-body">
      <div class="evidence-context" role="status"><strong>{{ periodLabel(source.category) }} · {{ replay ? '审核回放' : '对比快照' }}</strong><time>{{ cutoff.replace('T', ' ') }}</time><span>{{ currentBars.length }} / {{ source.bars.length }} 根</span><button v-if="replay" :disabled="busy || loading" @click="restore">返回审核快照末尾</button></div>
      <p class="evidence-boundary">仅核验所选周期的原始快照。此处确认回放只更新下方证据，不改变双图的共同截止；“返回图表”定位原对比快照，不将另一周期的结果混用。</p>
      <p v-if="loading" role="status" class="evidence-boundary">正在重建审核时刻；下方暂保留上一次已完成的核验结果。</p>
      <p v-if="error" role="alert" class="evidence-error">{{ error }}；未替换原审核结果。</p>
      <SignalEvidenceWorkspace ref="workspace" :key="context" :result="currentResult" :bars="currentBars" :total="source.bars.length" :busy="busy || loading" @seek="seek" @return-chart="emit('locate', $event)" @locate-divergence="emit('locateDivergence', $event, false)" @locate-reverse-pen="emit('locateDivergence', $event, true)" />
    </div>
  </details>
</template>

<style scoped>
.period-evidence { margin-top: 16px; min-width: 0; }
.evidence-context { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; font-size: 11px; padding: 10px 0; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
.evidence-context strong { color: var(--text); font-weight: 550; }
.evidence-context time, .evidence-context span { color: var(--text-dim); }
.evidence-context button { min-height: 32px; font-size: 11px; }
.evidence-boundary { font-size: 11px; line-height: 1.8; color: var(--text-muted); margin: 12px 0; }
.evidence-error { font-size: 12px; line-height: 1.8; color: #e6af81; overflow-wrap: anywhere; }
</style>
