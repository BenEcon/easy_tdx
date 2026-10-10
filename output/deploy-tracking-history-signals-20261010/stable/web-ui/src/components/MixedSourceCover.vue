<script setup lang="ts">
import { computed } from 'vue'
import type { MixedSourceCover } from '../types'
import { sourceRole, visibleMixedCover } from '../mixed-sources'
import { decompositionRange } from '../decomposition-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'

const props = defineProps<{ data?: MixedSourceCover; revisionId: string; expected: number[]; asOf: number; visibleCount: number; total: number; busy: boolean }>()
const emit = defineEmits<{ seek: [position: number] }>()
const cover = computed(() => visibleMixedCover(props.data, props.revisionId, props.expected, props.asOf, props.visibleCount))
</script>

<template>
  <details class="mixed-sources">
    <summary>混合层级来源 <span>{{ cover ? (cover.status === 'blocked' ? '边界待重组' : `${cover.blocks.length} 组来源`) : '待核验' }}</span></summary>
    <template v-if="cover">
      <p>来源截至 {{ cover.as_of_date ?? '日期未提供' }}。高层证明整体保留，基础线段按当前归属分组；不代表自然走势完成。</p>
      <p v-if="cover.joint_regrouping_required" class="notice">{{ cover.status === 'blocked' ? '证明跨出当前来源范围或存在重叠，暂停生成来源序列；需要扩大范围整体核验。' : '高层证明跨越当前分区边界，需要整体重组，不能沿分区切碎。' }}</p>
      <ol v-if="cover.status === 'covered'" aria-label="混合层级来源序列">
        <li v-for="(block, i) in cover.blocks" :key="i">
          <header><strong>{{ block.kind === 'extension_proof' ? `L${block.level} 延伸证明` : '基础线段组' }}</strong><span>{{ decompositionRange(block.source_segment_indices) }}</span></header>
          <p class="roles"><span v-for="(role, j) in block.role_spans" :key="j">{{ sourceRole(role.role) }} · {{ decompositionRange(role.source_segment_indices) }}</span></p>
          <p v-if="block.crosses_role_boundary" class="notice">跨分区 · 保留为一个整体</p>
          <ConfirmationReplay v-if="block.kind === 'extension_proof'" :index="block.known_index" :total="total" :busy="busy" label="延伸证明确认" @seek="emit('seek', $event)" />
        </li>
      </ol>
      <ul v-else aria-label="来源冲突">
        <li v-for="conflict in cover.conflicts" :key="conflict.proof_id + conflict.reason">{{ conflict.reason === 'proof_crosses_window' ? '证明超出当前范围' : '证明来源重叠' }} · {{ decompositionRange(conflict.source_segment_indices) }}</li>
      </ul>
    </template>
    <p v-else>未提供匹配的混合来源，请重新分析。</p>
  </details>
</template>

<style scoped>
.mixed-sources { margin-top: 10px; border-top: 1px solid var(--border); min-width: 0; }
summary { cursor: pointer; padding: 10px 0; color: var(--text); }
summary > span { margin-left: 10px; font-size: 11px; color: var(--text-dim); }
summary:hover { color: var(--accent); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
p, ul { margin: 6px 0; line-height: 1.8; color: var(--text-dim); overflow-wrap: anywhere; }
ol { list-style: none; padding: 0; margin: 8px 0; }
ol > li { padding: 10px 0 10px 12px; border-left: 2px solid var(--border); }
ol > li + li { border-top: 1px solid var(--border); }
header { display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline; }
strong { font-weight: 550; color: var(--text); }
header > span { margin-left: auto; color: var(--text-dim); font-variant-numeric: tabular-nums; }
.roles { display: flex; flex-wrap: wrap; gap: 3px 16px; }
.notice { color: var(--text); }
@media (max-width: 700px) { header > span { margin-left: 0; } }
</style>
