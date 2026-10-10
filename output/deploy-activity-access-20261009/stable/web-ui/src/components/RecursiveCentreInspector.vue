<script setup lang="ts">
import type { RecursiveStructureLayer } from '../types'
import ConfirmationReplay from './ConfirmationReplay.vue'
import { engineeringSource as source, engineeringValue as value, recursiveRelation, admissionReason } from '../engineering-trend-evidence'
import { centreState } from '../structure-evidence'
import { decompositionRange } from '../decomposition-evidence'

withDefaults(defineProps<{ layers?: RecursiveStructureLayer[]; total: number; busy: boolean; prefix?: 'M' | 'T' }>(), { prefix: 'T' })
const emit = defineEmits<{ seek: [position: number] }>()
</script>

<template>
  <details class="recursive-centres">
    <summary><strong>高层中枢进程</strong><span>已确认走势的中枢与延伸证据</span></summary>
    <dl class="research-copy"><div><dt>进程保留</dt><dd>即使下一层走势尚未完成，也保留本层中枢进程。</dd></div><div><dt>计算范围</dt><dd>每条连续链独立计算，{{ prefix }}1、{{ prefix }}2 为工程递归层级，不代表图表周期。</dd></div></dl>
    <p v-if="!layers" class="research-empty">此快照未包含高层中枢进程，请重新分析。</p>
    <p v-else-if="!layers.length" class="research-empty">尚无已确认走势可供高层中枢使用。</p>
    <section v-for="layer in layers" :key="layer.input_level" :aria-label="`${prefix}${layer.input_level} 来源中枢`">
      <h4>{{ prefix }}{{ layer.input_level }} 来源中枢 <span>{{ layer.chains.length }} 条独立连续链</span></h4>
      <section v-for="(chain, chainIndex) in layer.chains" :key="chain.id" class="chain">
        <p class="chain-title">连续链 {{ chainIndex + 1 }} · {{ chain.input_ids.length }} 个已确认输入</p>
        <p v-if="!chain.centres.length">尚未形成三单元共同重叠区。</p>
        <details v-for="(centre, index) in chain.centres" :key="centre.id" class="centre-row">
          <summary><strong>中枢 {{ index + 1 }}</strong><span>{{ centreState(centre.state) }} · 形成于 {{ centre.formed_date ?? '日期未提供' }}</span></summary>
          <dl class="research-facts">
            <dt>固定核心</dt><dd>{{ value(centre.zd) }}–{{ value(centre.zg) }}</dd>
            <dt>已纳入外围</dt><dd>{{ value(centre.low) }}–{{ value(centre.high) }}</dd>
            <dt>当前关系</dt><dd>{{ recursiveRelation(centre.relation_current) }}</dd>
            <dt>原始来源</dt><dd>{{ decompositionRange(centre.source_segment_indices) }}</dd>
            <dt v-if="centre.departure_id">离开来源</dt><dd v-if="centre.departure_id">{{ source(centre.departure_id) }}（不占用已纳入来源）</dd>
            <dt v-if="centre.return_id">回试来源</dt><dd v-if="centre.return_id">{{ source(centre.return_id) }} · {{ centre.exited_date ?? '日期未提供' }}</dd>
          </dl>
          <details class="evidence"><summary>查看来源与接纳时间</summary>
            <ul><li v-for="entry in centre.member_admissions" :key="entry.unit_id">
              {{ source(entry.unit_id) }} · {{ admissionReason(entry.reason) }}<br>
              单元确认 {{ entry.unit_confirmed_date ?? '未提供' }}；接纳 {{ entry.admitted_date ?? '未提供' }}；依据 {{ source(entry.witness_id) }}
            </li></ul>
          </details>
          <details class="evidence"><summary>查看 {{ centre.transitions.length }} 条状态记录</summary>
            <ul><li v-for="(event, eventIndex) in centre.transitions" :key="eventIndex">{{ event.known_date ?? '未提供' }} · {{ centreState(event.state) }} · {{ source(event.unit_id) }}</li></ul>
          </details>
          <ConfirmationReplay :index="centre.formed_index" :total="total" :busy="busy" :label="`${prefix}${layer.input_level} 来源中枢 ${index + 1} 形成`" @seek="emit('seek', $event)" />
          <ConfirmationReplay v-if="centre.exited_index !== null" :index="centre.exited_index" :total="total" :busy="busy" :label="`中枢 ${index + 1} 回试退出`" @seek="emit('seek', $event)" />
        </details>
        <details v-for="proof in chain.extension_proofs" :key="proof.id" class="centre-row">
          <summary><strong>{{ proof.source_unit_ids.length }} 单元延伸证明</strong><span>确认于 {{ proof.known_date ?? '日期未提供' }}</span></summary>
          <p>重叠核心 {{ value(proof.zd) }}–{{ value(proof.zg) }}；{{ decompositionRange(proof.source_segment_indices) }}。这是延伸重组证明，不是新的已完成走势。</p>
          <details class="evidence"><summary>查看延伸来源与确认依据</summary>
            <ul><li v-for="entry in proof.member_admissions" :key="entry.unit_id">{{ source(entry.unit_id) }} · 接纳 {{ entry.admitted_date ?? '未提供' }} · 依据 {{ source(entry.witness_id) }}</li></ul>
          </details>
          <ConfirmationReplay :index="proof.known_index" :total="total" :busy="busy" label="高层延伸" @seek="emit('seek', $event)" />
        </details>
      </section>
    </section>
    <p class="boundary research-caveat"><strong>使用边界</strong><span>中枢形成、回试退出、延伸证明都不等于盘整结束；本区不新增买卖点，也不把这些中枢直接当成已完成走势继续递归。</span></p>
  </details>
</template>

<style scoped>
.recursive-centres { margin-top: 14px; border-top: 1px solid var(--border); min-width: 0; font-size: 12px; }
summary { padding: 9px 0; line-height: 1.8; cursor: pointer; overflow-wrap: anywhere; }
strong, h4 { color: var(--text); font-weight: 550; font-size: 12px; }
strong { margin-right: 12px; }
summary span, p, dt, li, h4 span { color: var(--text-muted); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
h4 { margin: 16px 0 8px; } h4 span { margin-left: 10px; font-size: 11px; font-weight: 400; }
p { margin: 6px 0 12px; line-height: 1.8; overflow-wrap: anywhere; }
.chain-title { font-size: 11px; margin: 12px 0 6px; }
.centre-row { border-top: 1px solid var(--border); }
dl { display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: 7px 12px; line-height: 1.8; margin: 8px 0; }
dd { margin: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.evidence summary { font-size: 11px; padding: 5px 0; color: var(--text-muted); }
ul { padding-left: 18px; margin: 5px 0 12px; } li { line-height: 1.8; margin-bottom: 7px; overflow-wrap: anywhere; }
.boundary { border-top: 1px solid var(--border); padding-top: 10px; margin-top: 12px; }
@media (max-width: 600px) { summary span { display: block; margin-left: 16px; } h4 span { display: block; margin-left: 0; } dl { grid-template-columns: 76px minmax(0, 1fr); gap: 7px; } }
</style>
