<script setup lang="ts">
import { computed } from 'vue'
import type { ExpansionRegrouping, RegroupingVersions as VersionsData } from '../types'
import { decompositionRange } from '../decomposition-evidence'
import {
  candidateAudit, matchingPartAudit, expansionStatus, partitionSelection,
  completionStatus, completionReason, evidencePrice, evidenceRange,
  oppositeEvidence,
} from '../expansion-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'
import { expansionFocus } from '../expansion-focus'
import RegroupingVersions from './RegroupingVersions.vue'

const props = defineProps<{ data?: ExpansionRegrouping; versions?: VersionsData; total: number; visibleCount: number; busy: boolean }>()
const emit = defineEmits<{ seek: [position: number]; locate: [candidateId: string] }>()
const rows = computed(() => (props.data?.candidates ?? []).map(candidate => {
  const audit = candidateAudit(props.data, candidate)
  return {
    candidate, audit, locatable: expansionFocus(candidate, props.visibleCount, '') !== null,
    parts: candidate.parts.map((part, index) => {
      const partAudit = matchingPartAudit(audit, part, index)
      return { part, label: String.fromCharCode(65 + index), audit: partAudit,
        opposite: oppositeEvidence(candidate, part, partAudit, props.visibleCount) }
    }),
  }
}))
</script>

<template>
  <details class="expansion-inspector">
    <summary class="section-heading">
      <strong>跨中枢候选核验</strong>
      <span>{{ data ? `${rows.length} 项候选 · 不用于高层级信号` : '未提供候选依据' }}</span>
    </summary>
    <p class="scope">本区检查跨中枢的连续重组。分区 A/B/C 不是 MACD 柱色分段；切分成立、端点一致均不代表自然走势完成。</p>
    <p v-if="data?.rejected_suffix_count" class="scope">{{ data.rejected_suffix_count }} 条未确认或无效后缀未参与计算。</p>
    <ol v-if="rows.length" class="candidate-list">
      <li v-for="({ candidate, audit, parts, locatable }, index) in rows" :key="candidate.id">
        <details class="candidate">
          <summary class="candidate-heading">
            <strong>候选 {{ index + 1 }}</strong>
            <span>中枢 {{ candidate.centre_indices.map(id => id + 1).join(' / ') }}</span>
            <small>{{ expansionStatus(candidate.status) }}</small>
          </summary>
          <div class="candidate-content">
            <RegroupingVersions :data="versions" :candidate-id="candidate.id" :visible-count="visibleCount" :total="total" :busy="busy" @seek="emit('seek', $event)" />
            <strong>初次形成依据</strong>
            <dl class="facts">
              <div><dt>来源</dt><dd>{{ decompositionRange(candidate.source_segment_indices) }}</dd></div>
              <div><dt>旧外围交集</dt><dd>{{ evidenceRange(candidate.envelope_overlap) }}</dd></div>
              <div><dt>候选核心</dt><dd>{{ evidenceRange(candidate.candidate_core) }}</dd></div>
              <div><dt>依据可知于</dt><dd>{{ candidate.known_date ?? (candidate.known_index === null ? '等待两中枢退出' : '日期未提供') }}</dd></div>
            </dl>
            <p v-if="parts.length" class="scope">{{ partitionSelection(candidate.partition_selection) }}。候选核心不等于已确认的高级别中枢。</p>
            <p v-else class="scope">{{ expansionStatus(candidate.status) }}，当前不生成重组分区或高级别买卖点。</p>
            <div v-if="locatable" class="locate-action">
              <button :disabled="busy" :aria-label="`候选 ${index + 1}：定位重组区间`" @click="emit('locate', candidate.id)">定位重组区间</button>
              <span>仅定位 A/B/C 来源，不改变回放时刻</span>
            </div>
            <ConfirmationReplay :index="candidate.known_index" :total="total" :busy="busy" :label="`候选 ${index + 1} · 核验依据`" @seek="emit('seek', $event)" />
            <p v-if="audit" class="audit-time">完成依据核验截至 {{ audit.as_of_date ?? '日期未提供' }}；与候选初次可知时间分开记录。</p>
            <ol v-if="parts.length" class="part-list">
              <li v-for="item in parts" :key="item.label">
                <header class="part-heading">
                  <strong>分区 {{ item.label }} · {{ item.part.direction === 'up' ? '向上' : '向下' }}</strong>
                  <span>{{ completionStatus(item.audit?.status) }}</span>
                </header>
                <p class="part-source">{{ decompositionRange(item.part.source_segment_indices) }} · {{ item.part.start_date ?? '未提供' }} → {{ item.part.end_date ?? '未提供' }}</p>
                <dl class="facts">
                  <div><dt>起止价格</dt><dd>{{ evidencePrice(item.part.start_value) }} → {{ evidencePrice(item.part.end_value) }}</dd></div>
                  <div><dt>完整范围</dt><dd>{{ evidenceRange([item.part.low, item.part.high]) }}</dd></div>
                </dl>
                <template v-if="item.audit">
                  <p v-if="!item.audit.start_is_extreme" class="conflict">起点 {{ evidencePrice(item.part.start_value) }}，应对照区间{{ item.part.direction === 'up' ? '最低' : '最高' }} {{ evidencePrice(item.audit.start_extreme) }}。</p>
                  <p v-if="!item.audit.end_is_extreme" class="conflict">终点 {{ evidencePrice(item.part.end_value) }}，应对照区间{{ item.part.direction === 'up' ? '最高' : '最低' }} {{ evidencePrice(item.audit.end_extreme) }}。</p>
                  <p v-if="item.audit.opposite_segment_index !== null" class="scope">反向基础线段 {{ item.audit.opposite_segment_index + 1 }} · 确认于 {{ item.audit.opposite_known_date ?? '未提供' }}。仅是基础转折，不是同级别完成证明。</p>
                  <template v-if="item.opposite">
                    <p class="part-source">{{ item.opposite.sourceLabel }}。</p>
                    <dl class="facts">
                      <div><dt>反向起止</dt><dd class="date-range"><span>{{ item.opposite.start_date ?? '未提供' }}</span><span>→</span><span>{{ item.opposite.end_date ?? '未提供' }}</span></dd></div>
                      <div><dt>反向价格</dt><dd>{{ evidencePrice(item.opposite.start_value) }} → {{ evidencePrice(item.opposite.end_value) }}</dd></div>
                    </dl>
                  </template>
                  <p v-else-if="item.audit.opposite_segment_index !== null" class="part-source">反向线段起止或归属未提供、超出当前快照或不匹配，请重新分析。</p>
                  <ul class="reasons" aria-label="尚缺依据"><li v-for="reason in item.audit.blocking_reasons" :key="reason">{{ completionReason(reason) }}</li></ul>
                  <ConfirmationReplay :index="item.audit.opposite_known_index" :total="total" :busy="busy" :label="`候选 ${index + 1} · 分区 ${item.label} 反向线段`" @seek="emit('seek', $event)" />
                </template>
                <p v-else class="scope">缺少匹配的完成依据，请重新分析；不能据此认定走势完成。</p>
              </li>
            </ol>
          </div>
        </details>
      </li>
    </ol>
    <p v-else class="scope">{{ data ? '当前快照没有符合准入条件的跨中枢候选，不强行重组。' : '此结果未包含跨中枢核验数据，请重新分析。' }}</p>
  </details>
</template>

<style scoped>
.expansion-inspector { grid-column: 1 / -1; min-width: 0; border-top: 1px solid var(--border); padding-top: 14px; font-size: 12px; }
summary { cursor: pointer; line-height: 1.7; padding: 9px 0; }
strong { color: var(--text); font-weight: 550; }
.section-heading strong { margin-right: 12px; }
summary span, summary small, p, dt, .reasons { color: var(--text-dim); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }
.scope, .audit-time, .part-source, .conflict { margin: 6px 0 10px; line-height: 1.8; overflow-wrap: anywhere; }
.candidate-list, .part-list { list-style: none; padding: 0; margin: 0; }
.candidate-list > li, .part-list > li { border-top: 1px solid var(--border); }
.candidate-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.candidate-heading::before { content: '›'; color: var(--text-dim); transition: transform .15s ease; }
.candidate[open] > summary::before { transform: rotate(90deg); }
.candidate-heading:hover { background: var(--bg-hover, rgba(255,255,255,.025)); }
.candidate-heading small { margin-left: auto; }
.candidate-content { padding: 2px 12px 12px 20px; min-width: 0; }
.facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 24px; margin: 10px 0; font-variant-numeric: tabular-nums; }
.facts > div { display: grid; grid-template-columns: 6em minmax(0, 1fr); gap: 8px; align-items: baseline; }
dd { margin: 0; color: var(--text); overflow-wrap: anywhere; }
.date-range { display: flex; flex-wrap: wrap; gap: 2px 5px; }
.date-range span { white-space: nowrap; }
.part-list { margin-top: 12px; }
.part-list > li { padding: 12px 0 8px; }
.part-heading { display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: baseline; }
.part-heading span { margin-left: auto; font-size: 11px; color: var(--text-dim); }
.part-source, .audit-time { font-size: 11px; }
.conflict { color: var(--text); border-left: 2px solid var(--accent); padding-left: 10px; }
.reasons { padding-left: 18px; line-height: 1.8; margin: 8px 0; }
.locate-action { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 10px 0; font-size: 11px; color: var(--text-dim); }
.locate-action button { padding: 4px 9px; min-height: 28px; font-size: 11px; }
.locate-action button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 700px) {
  .facts { grid-template-columns: minmax(0, 1fr); }
  .section-heading span { display: block; margin-left: 16px; }
  .candidate-heading small { flex-basis: 100%; margin-left: 16px; }
  .part-heading span { flex-basis: 100%; margin-left: 0; }
  .candidate-content { padding-right: 0; padding-left: 16px; }
}
@media (prefers-reduced-motion: reduce) { .candidate-heading::before { transition: none; } }
</style>
