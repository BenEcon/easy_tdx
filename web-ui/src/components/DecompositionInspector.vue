<script setup lang="ts">
import type { BaseDecomposition } from '../types'
import { decompositionCoverage, decompositionRange, decompositionRole } from '../decomposition-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'

defineProps<{ data?: BaseDecomposition; total: number; busy: boolean }>()
const emit = defineEmits<{ seek: [position: number] }>()
</script>

<template>
  <details class="decomposition-inspector research-panel">
    <summary><strong>走势分解审核</strong><span>{{ decompositionCoverage(data) }}</span></summary>
    <div class="research-panel-body">
    <p class="scope">这是基础线段的归属分解。“归属固定”不代表走势类型完成，未用于高层级递归。</p>
    <ol v-if="data?.blocks.length">
      <li v-for="(block, index) in data.blocks" :key="`${block.role}-${block.segment_indices[0]}`">
        <details>
          <summary>
            <span class="ordinal">{{ index + 1 }}</span>
            <strong>{{ decompositionRole(block.role) }}</strong>
            <span class="block-source">{{ decompositionRange(block.segment_indices) }}</span>
            <small class="block-status" :class="{ pending: !block.ownership_frozen }">{{ block.ownership_frozen ? '归属固定' : '仍可演化' }}</small>
          </summary>
          <div class="block-evidence">
            <dl class="block-facts">
              <div><dt>价格范围</dt><dd>{{ block.low.toFixed(2) }}–{{ block.high.toFixed(2) }}</dd></div>
              <div><dt>归属可知于</dt><dd>{{ block.known_date ?? '未提供' }}</dd></div>
              <div v-if="block.centre_index !== null"><dt>关联中枢</dt><dd>中枢 {{ block.centre_index + 1 }}</dd></div>
            </dl>
            <p v-if="block.role === 'pending_departure'">等待回试确认；回到中枢时可能重新纳入中枢组成段。</p>
            <p v-else-if="block.role === 'unassigned'">当前证据尚不足以归入中枢或连接段，保留原始线段。</p>
            <ConfirmationReplay :index="block.known_index" :total="total" :busy="busy" :label="`分解 ${index + 1} 归属`" @seek="emit('seek', $event)" />
          </div>
        </details>
      </li>
    </ol>
    <p v-else class="scope">{{ data ? '当前没有可审核的已确认线段。' : '此结果未包含分解依据，请重新分析。' }}</p>
    </div>
  </details>
</template>

<style scoped>
.decomposition-inspector { grid-column: 1 / -1; min-width: 0; border-top: 1px solid var(--border); padding-top: 14px; font-size: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.6; }
summary strong { color: var(--text); font-weight: 550; margin-right: 12px; }
summary span, summary small, .scope, .block-evidence { color: var(--text-dim); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 5px; }
.scope { line-height: 1.7; margin: 5px 0 12px; }
ol { padding: 0; margin: 0; list-style: none; }
li { border-top: 1px solid var(--border); }
li summary { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
li summary::before { content: '›'; transition: transform .15s ease; color: var(--text-dim); }
li details[open] > summary::before { transform: rotate(90deg); }
li summary:hover { background: var(--bg-hover, rgba(255,255,255,.025)); }
li summary strong { margin-right: 0; }
li summary small { margin-left: auto; white-space: nowrap; }
.ordinal { min-width: 20px; font-variant-numeric: tabular-nums; }
.block-evidence { padding: 0 12px 10px 32px; overflow-wrap: anywhere; }
.block-evidence p { margin: 5px 0; line-height: 1.7; font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: reduce) { li summary::before { transition: none; } }
</style>
