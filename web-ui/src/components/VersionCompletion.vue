<script setup lang="ts">
import { computed } from 'vue'
import type { RegroupingRevision, VersionCompletionAudit } from '../types'
import { versionCompletion } from '../version-completion'
import { completionReason, completionStatus, evidencePrice, oppositeEvidence } from '../expansion-evidence'
import { decompositionRange } from '../decomposition-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'
import { componentCentres, componentSummary } from '../component-centres'

const props = defineProps<{ audit?: VersionCompletionAudit; revision: RegroupingRevision; asOf: number; visibleCount: number; total: number; busy: boolean }>()
const emit = defineEmits<{ seek: [position: number] }>()
const matched = computed(() => versionCompletion(props.audit, props.revision, props.asOf, props.visibleCount))
const rows = computed(() => matched.value?.parts.map((audit, i) => {
  const part = props.revision.parts[i]!
  return { audit, part, opposite: oppositeEvidence(props.revision, part, audit, props.asOf + 1) }
}) ?? [])
</script>

<template>
  <details class="version-completion">
    <summary>本版完成依据 <span>第 {{ revision.version }} 版 · 自然完成待证</span></summary>
    <template v-if="matched">
      <p>核验截至 {{ matched.as_of_date ?? '日期未提供' }}，仅对应本版分区，不沿用初次形成的切分。</p>
      <ol aria-label="本版分区完成依据">
        <li v-for="({ audit: row, part, opposite }, i) in rows" :key="i">
          <header><strong>{{ String.fromCharCode(65 + i) }} · {{ decompositionRange(part.source_segment_indices) }}</strong><span>{{ completionStatus(row.status) }}</span></header>
          <p>{{ componentSummary(part) }} · 尚未证明自然完成</p>
          <details v-if="componentCentres(part)?.length" class="centre-chain">
            <summary>内部中枢依据</summary>
            <p v-for="(centre, j) in componentCentres(part)" :key="j">{{ j + 1 }} · {{ decompositionRange(centre.seed_segment_indices) }} · 核心 {{ evidencePrice(centre.zd) }}–{{ evidencePrice(centre.zg) }} · 外围 {{ evidencePrice(centre.low) }}–{{ evidencePrice(centre.high) }} · 形成于 {{ centre.formed_date ?? '日期未提供' }}</p>
          </details>
          <p v-if="!row.start_is_extreme">起点 {{ evidencePrice(part.start_value) }} 与区间方向极值 {{ evidencePrice(row.start_extreme) }} 不一致。</p>
          <p v-if="!row.end_is_extreme">终点 {{ evidencePrice(part.end_value) }} 与区间方向极值 {{ evidencePrice(row.end_extreme) }} 不一致。</p>
          <template v-if="opposite">
            <p>反向基础线段 {{ opposite.segment_index + 1 }} · {{ opposite.sourceLabel }}。</p>
            <p>确认于 {{ row.opposite_known_date ?? '日期未提供' }}；基础转折不等于同级别完成。</p>
            <ConfirmationReplay :index="opposite.known_index" :total="total" :busy="busy" :label="`第 ${revision.version} 版 ${String.fromCharCode(65 + i)} 反向线段`" @seek="emit('seek', $event)" />
          </template>
          <p v-else>尚无已确认的反向基础线段。</p>
        </li>
      </ol>
      <ul aria-label="本版尚缺依据"><li v-for="reason in matched.blocking_reasons" :key="reason">{{ completionReason(reason) }}</li></ul>
    </template>
    <p v-else>本版完成依据未提供、超出当前快照或不匹配，请重新分析。</p>
  </details>
</template>

<style scoped>
.version-completion { margin-top: 10px; border-top: 1px solid var(--border); min-width: 0; }
summary { cursor: pointer; padding: 10px 0; color: var(--text); }
summary > span { font-size: 11px; margin-left: 10px; color: var(--text-dim); }
summary:hover { color: var(--accent); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
ol { list-style: none; padding: 0; margin: 8px 0; }
ol > li { padding: 9px 0; border-bottom: 1px solid var(--border); }
header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 16px; }
strong { color: var(--text); font-weight: 550; }
header span { color: var(--text-dim); font-size: 11px; margin-left: auto; }
p, ul { color: var(--text-dim); line-height: 1.8; margin: 6px 0; overflow-wrap: anywhere; }
ul { padding-left: 18px; }
@media (max-width:700px) { header span { margin-left: 0; flex-basis: 100%; } }
</style>
