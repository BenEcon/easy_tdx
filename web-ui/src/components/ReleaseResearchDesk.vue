<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Bar, Category } from '../types'
import { replayReleaseHistory, replayReleaseComparison, formatError } from '../api'
import { historyStateLabel, validHistoryBatch, type ReleaseHistoryEvent, type ReleaseComparison } from '../release-review'
import { releaseEvidence, releaseReason } from '../released-evidence'
import { decompositionRange as range } from '../decomposition-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'
import ReleasedRecursionInspector from './ReleasedRecursionInspector.vue'
import ExhaustiveResearch from './ExhaustiveResearch.vue'

const props = defineProps<{ code: string; category: Category; bars: Bar[]; total: number; busy: boolean }>()
const emit = defineEmits<{ seek: [position: number] }>()
const events = ref<ReleaseHistoryEvent[]>([]), through = ref(0), pending = ref(false), error = ref('')
const comparison = ref<ReleaseComparison | null>(null)
const policy = ref('earliest')
let version = 0, controller: AbortController | undefined
function cancel() { version++; controller?.abort(); pending.value = false }
function reset() { cancel(); events.value = []; through.value = 0; comparison.value = null; error.value = '' }
watch(() => [props.code, props.category, props.bars], reset)
watch(() => props.busy, busy => { if (busy) cancel() })
onBeforeUnmount(cancel)
const selected = computed(() => comparison.value?.variants.find(v => v.policy === policy.value))
const policies: Record<string, string> = {earliest: '默认 · 最早可用优先', widest: '研究 · 较宽来源优先', latest: '研究 · 较晚可用优先'}
async function load(mode: 'history' | 'comparison') {
  if (props.busy || pending.value || !props.bars.length) return
  const run = ++version; controller = new AbortController(); pending.value = true; error.value = ''
  const request = {code: props.code, category: props.category, bars: props.bars, visible_count: props.bars.length}
  try {
    if (mode === 'history') {
      for (let start = through.value + 1; start <= request.visible_count; start += 40) {
        const end = Math.min(start + 39, request.visible_count)
        const batch = await replayReleaseHistory({...request, start_count: start, visible_count: end}, controller.signal)
        if (run !== version) return
        if (!validHistoryBatch(batch, start, end)) throw new Error('历史批次无法核验，未接纳该批结果')
        events.value.push(...batch.events); through.value = end
      }
    } else {
      const next = await replayReleaseComparison(request, controller.signal)
      if (run !== version) return
      if (next.scope !== 'bounded_selection_comparison_v1' || next.exhaustive !== false
        || next.eligible_for_trading !== false || next.default_policy !== 'earliest'
        || next.variants.length !== 3 || new Set(next.variants.map(v => v.policy)).size !== 3
        || next.variants.some(v => !policies[v.policy] || !releaseEvidence(v.snapshot, request.visible_count))) {
        throw new Error('研究比较来源无法核验，未展示替代结果')
      }
      comparison.value = next; policy.value = 'earliest'
    }
  } catch (e) { if (run === version) error.value = formatError(e) }
  finally { if (run === version) pending.value = false }
}
</script>

<template>
  <details class="research-desk research-panel research-hierarchy">
    <summary><strong>归属时间轴与分解研究</strong><span>按需计算 · 不改变默认分析</span></summary>
    <div class="research-panel-body">
    <ExhaustiveResearch :code="code" :category="category" :bars="bars" :total="total" :busy="busy || pending" @seek="emit('seek', $event)" />
    <dl class="research-copy"><div><dt>重建方式</dt><dd>使用当前复权快照逐根截断、重新识别笔和线段，再计算归属。</dd></div><div><dt>数据版本</dt><dd>不是交易日当时保存的数据版本，也不把最新结果倒填过去。</dd></div></dl>
    <div class="actions">
      <button :disabled="busy || pending || through === bars.length" @click="load('history')">{{ through === bars.length ? '时间轴已完成' : through ? '继续重建时间轴' : '重建归属时间轴' }}</button>
      <button :disabled="busy || pending" @click="load('comparison')">比较研究分解</button>
      <button v-if="pending" @click="cancel">停止加载</button>
      <span aria-live="polite">{{ through }} / {{ bars.length }} 根已重建{{ pending ? ' · 计算中' : '' }}</span>
    </div>
    <p v-if="error" class="research-error" role="alert">{{ error }}</p>
    <details v-if="through" class="reading-disclosure"><summary>逐日状态变化 · {{ events.length }} 项{{ through < bars.length ? '（尚未加载完整）' : '' }}</summary>
      <p v-if="!events.length">已核验区间没有完成走势或归属区的状态变化，不代表剩余区间也没有变化。</p>
      <div class="timeline">
        <details v-for="(event, i) in events" :key="`${event.id}-${event.index}-${i}`">
          <summary>{{ event.date }} · {{ (event.after ?? event.before)!.kind === 'domain' ? '归属区' : '走势' }} · {{ event.change === 'added' ? '出现' : event.change === 'removed' ? '本前缀不再保留' : '状态更新' }}</summary>
          <p>{{ range((event.after ?? event.before)!.source_segment_indices) }}：{{ historyStateLabel(event.before) }} → {{ historyStateLabel(event.after) }}</p>
          <p v-if="event.after?.required_parent_level">该归属区要求至少 M{{ event.after.required_parent_level }} 父走势完整覆盖，并独立通过完成判据。</p>
          <p v-if="event.after?.current_placement?.reason">本次未准入原因：{{ releaseReason(event.after.current_placement.reason) }}</p>
          <ConfirmationReplay :index="event.index" :total="total" :busy="busy || pending" label="本次状态变化" @seek="emit('seek', $event)" />
        </details>
      </div>
    </details>
    <section v-if="comparison">
      <dl class="research-copy"><div><dt>比较范围</dt><dd>只比较三种确定性的候选选择顺序，未穷举所有合法结合律分解。</dd></div><div><dt>独立核验</dt><dd>每种结果均重新执行高层结构、MACD、反向确认与归属门槛；较晚可用优先仅用于当前截面的研究，不预知后续行情。结果可能完全一致。</dd></div></dl>
      <div class="policies" role="group" aria-label="研究选择顺序">
        <button v-for="variant in comparison.variants" :key="variant.policy" :aria-pressed="policy === variant.policy" @click="policy = variant.policy">{{ policies[variant.policy] }}</button>
      </div>
      <p v-if="selected">当前方案：{{ policies[selected.policy] }} · 外部 {{ selected.snapshot.external_frontier_ids.length }} 条，最高 M{{ selected.snapshot.highest_external_level }}，未解决基础来源 {{ selected.snapshot.unresolved_segment_indices.length }} 条。</p>
      <p class="research-caveat"><strong>回放口径</strong><span>此处回放按钮重算对应日期的默认分析，不将研究方案写入主图或交易策略。</span></p>
      <ReleasedRecursionInspector v-if="selected" :data="selected.snapshot" :total="total" :busy="busy || pending" :locatable="false" @seek="emit('seek', $event)" />
    </section>
    </div>
  </details>
</template>

<style scoped>
.research-desk { grid-column: 1 / -1; min-width: 0; border-top: 1px solid var(--border); font-size: 12px; padding-top: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.8; overflow-wrap: anywhere; }
summary span { margin-left: 12px; color: var(--text-muted); }
strong { font-weight: 550; }
p { color: var(--text-muted); line-height: 1.8; margin: 8px 0; overflow-wrap: anywhere; }
.actions, .policies { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.actions span { color: var(--text-muted); font-size: 11px; }
button { min-height: 28px; padding: 4px 9px; font-size: 11px; line-height: 1.6; white-space: normal; }
button[aria-pressed=true] { border-color: var(--accent); background: rgba(74,158,255,.08); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.timeline { max-height: 440px; overflow: auto; }
.timeline > details { border-top: 1px solid var(--border); }
@media (max-width: 560px) { summary span { display: block; margin-left: 0; } }
</style>
