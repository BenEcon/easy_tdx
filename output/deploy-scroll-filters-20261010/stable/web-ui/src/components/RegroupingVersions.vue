<script setup lang="ts">
import { computed } from 'vue'
import type { RegroupingVersions } from '../types'
import { visibleRegroupingCase, regroupingReason, regroupingStatus } from '../regrouping-versions'
import { decompositionRange } from '../decomposition-evidence'
import { evidenceRange } from '../expansion-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'
import MixedSourceCover from './MixedSourceCover.vue'
import VersionCompletion from './VersionCompletion.vue'
import { componentSummary } from '../component-centres'

const props = defineProps<{
  data?: RegroupingVersions; candidateId: string; visibleCount: number; total: number; busy: boolean
}>()
const emit = defineEmits<{ seek: [position: number] }>()
const item = computed(() => visibleRegroupingCase(props.data, props.candidateId, props.visibleCount))
const current = computed(() => item.value?.revisions.at(-1))
const history = computed(() => item.value?.revisions.slice(0, -1).reverse() ?? [])
</script>

<template>
  <section class="regrouping-versions" aria-label="当前重组与历史版本">
    <template v-if="item && current">
      <header><strong>当前重组 · 第 {{ current.version }} 版</strong><span>{{ regroupingStatus(current.status) }}</span></header>
      <p>更新于 {{ current.known_date ?? '日期未提供' }} · {{ regroupingReason(current.reason) }}</p>
      <p>候选核心 {{ evidenceRange(current.candidate_core) }} · {{ decompositionRange(current.source_segment_indices) }}</p>
      <p v-if="current.retained_prefix_segment_indices?.length">保留前缀：{{ decompositionRange(current.retained_prefix_segment_indices) }}。已移出当前切分，等待重新归属，不代表该部分走势完成。</p>
      <ol v-if="current.parts.length" class="parts" aria-label="当前分区">
        <li v-for="(part, i) in current.parts" :key="i">
          <strong>{{ String.fromCharCode(65 + i) }} · {{ part.direction === 'up' ? '向上' : '向下' }}</strong>
          <span>{{ decompositionRange(part.source_segment_indices) }}</span>
          <span>{{ evidenceRange([part.low, part.high]) }}</span>
          <small class="component-kind">{{ componentSummary(part) }}</small>
        </li>
      </ol>
      <p v-if="current.higher_proof_ids.length">已有更高层级延伸证明与此来源重叠，暂停平铺切分；请结合上方延伸证明核验。这不代表自然走势完成。</p>
      <p v-if="item.pending_segment_indices.length">待归入后续结构：{{ decompositionRange(item.pending_segment_indices) }}</p>
      <ConfirmationReplay :index="current.known_index" :total="total" :busy="busy" label="当前重组版本" @seek="emit('seek', $event)" />
      <VersionCompletion :audit="item.completion_audit" :revision="current" :as-of="item.as_of_index" :visible-count="visibleCount" :total="total" :busy="busy" @seek="emit('seek', $event)" />
      <MixedSourceCover :data="item.mixed_source_cover" :revision-id="current.id" :expected="[...(current.retained_prefix_segment_indices ?? []), ...current.source_segment_indices, ...item.pending_segment_indices]" :as-of="item.as_of_index" :visible-count="visibleCount" :total="total" :busy="busy" @seek="emit('seek', $event)" />
      <details v-if="history.length" class="history">
        <summary>历史版本 · {{ history.length }} 次</summary>
        <ol>
          <li v-for="revision in history" :key="revision.id">
            <header><strong>第 {{ revision.version }} 版</strong><span>{{ regroupingStatus(revision.status) }}</span></header>
            <p>{{ revision.known_date ?? '日期未提供' }} · {{ regroupingReason(revision.reason) }}</p>
            <p>候选核心 {{ evidenceRange(revision.candidate_core) }} · {{ decompositionRange(revision.source_segment_indices) }}</p>
            <p v-if="revision.retained_prefix_segment_indices?.length">保留前缀：{{ decompositionRange(revision.retained_prefix_segment_indices) }} · 归属待定</p>
            <p v-if="revision.start_change?.detached_segment_indices.length">本版移出：{{ decompositionRange(revision.start_change.detached_segment_indices) }}</p>
            <p v-if="revision.start_change?.reincorporated_segment_indices.length">本版重新纳入：{{ decompositionRange(revision.start_change.reincorporated_segment_indices) }}</p>
            <p v-for="(part, i) in revision.parts" :key="i">{{ String.fromCharCode(65 + i) }}：{{ decompositionRange(part.source_segment_indices) }} · {{ componentSummary(part) }}</p>
            <ConfirmationReplay :index="revision.known_index" :total="total" :busy="busy" :label="`历史重组第 ${revision.version} 版`" @seek="emit('seek', $event)" />
            <VersionCompletion :audit="revision.completion_audit" :revision="revision" :as-of="revision.known_index" :visible-count="visibleCount" :total="total" :busy="busy" @seek="emit('seek', $event)" />
          </li>
        </ol>
      </details>
      <p class="scope">以下为初次形成的固定依据；当前解释可以改变，不覆盖旧记录或原信号确认时间。历史按当前数据快照与同一规则重建，不是行情修订前的存档。</p>
    </template>
    <p v-else>当前快照未提供匹配的重组版本；等待初次形成或重新分析。</p>
  </section>
</template>

<style scoped>
.regrouping-versions { border-bottom: 1px solid var(--border); padding: 12px 0; margin-bottom: 12px; min-width: 0; }
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 16px; }
header span { margin-left: auto; color: var(--text-dim); font-size: 11px; }
strong { font-weight: 550; color: var(--text); }
p { margin: 7px 0; line-height: 1.8; color: var(--text-dim); overflow-wrap: anywhere; }
.parts, .history ol { list-style: none; padding: 0; margin: 10px 0; }
.parts li { display: grid; grid-template-columns: 5em minmax(0, 1fr) auto; gap: 8px; padding: 7px 0; border-top: 1px solid var(--border); font-variant-numeric: tabular-nums; }
.parts span { overflow-wrap: anywhere; }
.component-kind { grid-column: 2 / -1; color: var(--text-dim); font-size: 11px; line-height: 1.6; }
summary { cursor: pointer; padding: 8px 0; color: var(--text); transition: color .15s ease; }
summary:hover { color: var(--accent); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
.history li { padding: 10px 0 10px 12px; border-left: 1px solid var(--border); }
.scope { font-size: 11px; }
@media (max-width: 700px) { header span { margin-left: 0; flex-basis: 100%; } .parts li { grid-template-columns: 5em minmax(0, 1fr); } .parts li > span:nth-of-type(2) { grid-column: 2; } }
@media (prefers-reduced-motion: reduce) { summary { transition: none; } }
</style>
