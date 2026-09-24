<script setup lang="ts">
import type { ExtensionProof } from '../types'
import ConfirmationReplay from './ConfirmationReplay.vue'

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
      <p>{{ proof.start_date }} → {{ proof.end_date }} · 本项证明可知于 {{ proof.known_date }}</p>
      <p>基础线段 {{ proof.source_segment_indices.map(i => i + 1).join('、') }}</p>
      <p>三个子区间：{{ proof.child_ranges.map(([low, high]) => `${low!.toFixed(2)}–${high!.toFixed(2)}`).join(' / ') }}</p>
      <p>区间交集为中枢核心；外围 {{ proof.low.toFixed(2) }}–{{ proof.high.toFixed(2) }}。重组来源不代表自然走势已结束。</p>
      <ConfirmationReplay v-if="root" :index="proof.known_index" :total="total" :busy="busy" :label="`结构 L${proof.level} 升级`" @seek="emit('seek', $event)" />
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
@media (max-width: 600px) { .proof-body { padding-left: 8px; } }
</style>
