<script setup lang="ts">
import type { ExtensionProof } from '../types'
import ConfirmationReplay from './ConfirmationReplay.vue'
import { admissionReason, admissionWitness } from '../extension-evidence'

defineProps<{ proof: ExtensionProof; total: number; busy: boolean; root?: boolean }>()
const emit = defineEmits<{ seek: [position: number] }>()
</script>

<template>
  <details class="extension-proof">
    <summary>
      <strong>{{ root ? '升级证明' : '重组来源' }} · 结构 L{{ proof.level }}</strong>
      <span>{{ proof.source_segment_indices.length }} 条基础线段</span>
      <span>{{ proof.zd.toFixed(2) }}–{{ proof.zg.toFixed(2) }}</span>
    </summary>
    <div class="proof-body">
      <dl class="research-copy">
        <div><dt>覆盖时间</dt><dd>{{ proof.start_date }} → {{ proof.end_date }}</dd></div>
        <div><dt>实际可知</dt><dd>{{ proof.known_date }}</dd></div>
        <div><dt>基础线段</dt><dd>{{ proof.source_segment_indices.map(i => i + 1).join('、') }}</dd></div>
        <div><dt>三个子区间</dt><dd>{{ proof.child_ranges.map(([low, high]) => `${low!.toFixed(2)}–${high!.toFixed(2)}`).join(' / ') }}</dd></div>
        <div><dt>重叠与外围</dt><dd>区间交集为中枢核心；外围 {{ proof.low.toFixed(2) }}–{{ proof.high.toFixed(2) }}。重组来源不代表自然走势已结束。</dd></div>
      </dl>
      <ConfirmationReplay :index="proof.known_index" :total="total" :busy="busy" :label="`${root ? '升级证明' : '重组来源'} L${proof.level}`" @seek="emit('seek', $event)" />
      <details v-if="proof.member_admissions?.length" class="admission-details">
        <summary>来源接纳时间 · {{ proof.member_admissions.length }} 条线段</summary>
        <p>沿用基础中枢的接纳记录。线段确认不等于已被接纳；分组外的回试线段仅作确认依据，不计入组成来源。</p>
        <ul class="admission-list">
          <li v-for="entry in proof.member_admissions" :key="entry.segment_index">
            <div class="admission-title"><strong>线段 {{ entry.segment_index + 1 }}</strong><span>{{ admissionReason(entry.reason) }}</span></div>
            <p>{{ admissionWitness(entry, proof.source_segment_indices) }}</p>
            <dl><div><dt>线段确认</dt><dd>{{ entry.segment_confirmed_date ?? '—' }}</dd></div><div><dt>基础中枢接纳</dt><dd>{{ entry.admitted_date ?? '—' }}</dd></div></dl>
            <ConfirmationReplay v-if="entry.reason === 'failed_departure_return'" :index="entry.admitted_index" :total="total" :busy="busy" :label="`线段 ${entry.segment_index + 1} 接纳`" @seek="emit('seek', $event)" />
          </li>
        </ul>
      </details>
      <ExtensionProofNode v-for="child in proof.children" :key="child.id" :proof="child" :total="total" :busy="busy" @seek="emit('seek', $event)" />
    </div>
  </details>
</template>

<style scoped>
.extension-proof { min-width: 0; border-top: 1px solid var(--border); font-size: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.7; overflow-wrap: anywhere; }
summary strong { font-weight: 550; color: var(--text); }
summary span { display: inline-block; margin-left: 12px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
summary:hover { background: var(--bg-hover, rgba(255,255,255,.025)); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
.proof-body { padding: 0 0 8px 16px; color: var(--text-dim); overflow-wrap: anywhere; }
p { margin: 6px 0; line-height: 1.8; }
.admission-details { margin: 10px 0; border-top: 1px solid var(--border); }
.admission-list { list-style: none; padding: 0; margin: 0; }
.admission-list li { padding: 9px 0; border-bottom: 1px solid var(--border); }
.admission-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; line-height: 1.7; }
.admission-title strong { color: var(--text); font-weight: 500; }
dl { display: flex; flex-wrap: wrap; gap: 6px 24px; margin: 5px 0 0; font-variant-numeric: tabular-nums; }
dl div { display: flex; flex-wrap: wrap; gap: 4px 8px; }
dt { color: var(--text-muted); }
dd { margin: 0; }
@media (max-width: 600px) { .proof-body { padding-left: 8px; } }
</style>
