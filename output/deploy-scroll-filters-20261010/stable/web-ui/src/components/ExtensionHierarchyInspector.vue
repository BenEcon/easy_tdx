<script setup lang="ts">
import type { ExtensionHierarchy } from '../types'
import ExtensionProofNode from './ExtensionProofNode.vue'

defineProps<{ data?: ExtensionHierarchy; total: number; busy: boolean }>()
const emit = defineEmits<{ seek: [position: number] }>()
</script>

<template>
  <details class="extension-inspector research-panel research-hierarchy">
    <summary><strong>延伸升级核验</strong><span>{{ data?.proofs.length ? `${data.proofs.length} 项证明 · 最高结构 L${data.highest_proven_level}` : '暂无可证明的升级' }}</span></summary>
    <div class="research-panel-body">
    <dl class="research-copy">
      <div><dt>核验输入</dt><dd>基础线段为最小输入，九段延伸按结合律逐层核验。</dd></div>
      <div><dt>层级含义</dt><dd><strong>L 是结构层级</strong>，不对应日线、周线；中枢形成不等于走势结束。</dd></div>
      <div v-if="data?.rejected_suffix_count"><dt>排除项</dt><dd><strong>{{ data.rejected_suffix_count }} 条</strong>未确认或无效后缀未参与计算。</dd></div>
    </dl>
    <ExtensionProofNode v-for="proof in data?.proofs" :key="proof.id" :proof="proof" :total="total" :busy="busy" root @seek="emit('seek', $event)" />
    <p v-if="!data" class="research-empty">此结果尚未包含升级证明，请重新分析。</p>
    <p v-else-if="!data.proofs.length" class="research-empty">当前快照没有满足本规则的延伸证明，不据线段数量或 MACD 柱色强行升级。</p>
    <p class="boundary research-caveat"><strong>使用边界</strong><span>本区仅验证延伸重组。两中枢扩展与自然走势完成的完整递归尚未接通，不用于新增买卖信号。</span></p>
    </div>
  </details>
</template>

<style scoped>
.extension-inspector { grid-column: 1 / -1; min-width: 0; border-top: 1px solid var(--border); padding-top: 14px; font-size: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.7; }
summary strong { font-weight: 550; color: var(--text); margin-right: 12px; }
summary span, p { color: var(--text-dim); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
p { margin: 6px 0 12px; line-height: 1.8; overflow-wrap: anywhere; }
.boundary { border-top: 1px solid var(--border); padding-top: 10px; }
</style>
