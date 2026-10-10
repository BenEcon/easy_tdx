<script setup lang="ts">
import { ref } from 'vue'
import type { Bar, ChanlunResult, ChanlunDivergence } from '../types'
import SignalEvidenceBrowser from './SignalEvidenceBrowser.vue'
import ResearchEventRecord from './ResearchEventRecord.vue'
import ConfirmationReplay from './ConfirmationReplay.vue'
import EvidenceReading from './EvidenceReading.vue'
import { structureDate } from '../structure-display'
import { signalName as signalLabel } from '../chart-signal-detail'
import { divergenceEvidence, divergenceName, signalEvidence, waveFailureSummary, waveDiagnosticLines, waveComparisonName, waveComparisonLines } from '../divergence-evidence'
import { divergenceFocus, reversePenFocus } from '../divergence-focus'
import { diagnosticEvidenceState, eventEvidenceState, evidenceStateLabels, signalEvidenceState, type EvidenceDateFocus } from '../signal-evidence-index'
defineProps<{ result: ChanlunResult; bars: Bar[]; total: number; busy: boolean; entry?: 'signals' | 'divergence' }>()
const emit = defineEmits<{ seek: [position: number]; locateDivergence: [item: ChanlunDivergence]; locateReversePen: [item: ChanlunDivergence]; returnChart: [date: string] }>()
const browser = ref<InstanceType<typeof SignalEvidenceBrowser>>()
defineExpose({ inspectDate: (focus: EvidenceDateFocus) => browser.value?.inspectDate(focus) })
function formatMessage(text: string): string {
  return text.replace(/-?\d+\.\d+/g, value => Number(value).toFixed(2))
}
</script>
<template>
  <div class="divergence-workspace signal-workspace">
            <SignalEvidenceBrowser ref="browser" :events="result.bcs" :signals="result.mmds" :diagnostics="result.wave_diagnostics" :entry="entry" @return-chart="emit('returnChart', $event)">
            <template #signals="{ items, count: matchCount }">
            <details v-if="matchCount" class="signal-records research-panel research-hierarchy" open>
              <summary><strong>结构性买卖点</strong><span>{{ matchCount }} 条匹配 · 展示 {{ items.length }} 条</span></summary>
              <div class="research-panel-body">
                <p class="event-scope-note">极值日期与确认日期分开记录；展开条目可查看结构依据与确认回放。</p>
            <ResearchEventRecord v-for="(signal, index) in items" :key="`${signal.type}-${signal.date}-${index}`" class="signal-record"
              :title="signalLabel(signal.type)" :date="signal.date" :tone="signal.type.includes('buy') ? 'buy' : 'sell'"
              :state="signalEvidenceState(signal)" :state-label="signal.confirmed_date ? '已确认' : '确认时间未提供'"
              :metadata="[{label:'确认日期',value:structureDate(signal.confirmed_date)},{label:'识别来源',value:signal.source === 'confirmed_segment_base_v1' ? '已确认线段 · 基础结构' : '原始信号记录'}]"
              :description="formatMessage(signal.msg)">
              <details v-if="signal.source === 'confirmed_segment_base_v1'" class="reading-disclosure">
                <summary>查看结构依据</summary>
                <div class="audit-evidence-body">
                <EvidenceReading :lines="signalEvidence(signal)" />
                <div class="event-replays"><ConfirmationReplay :index="signal.confirmed_index" :total="total" :busy="busy" :label="signalLabel(signal.type)" caption="结构确认" @seek="emit('seek', $event)" /></div>
                </div>
              </details>
            </ResearchEventRecord>
              </div>
            </details>
            </template>
            <template #prompts="{ items, count: matchCount }">
            <details v-if="matchCount" class="macd-records research-panel research-hierarchy" open>
              <summary><strong>MACD M1 提示</strong><span>{{ matchCount }} 条匹配 · 展示 {{ items.length }} 条</span></summary>
              <div class="research-panel-body">
                <p class="event-scope-note">独立于结构性买卖点，不参与一类点策略判断。</p>
              <ResearchEventRecord v-for="(item, index) in items" :key="`macd-prompt-${index}`" class="macd-prompt-row"
                :title="`M1 · ${item.direction === 'down' ? '买入提示' : '卖出提示'}`" :date="item.curr_date" :tone="item.direction === 'down' ? 'buy' : 'sell'" state="confirmed" state-label="提示已确认"
                :metadata="[{label:'实际确认',value:structureDate(item.confirmed_date)},{label:'提示来源',value:divergenceName(item)}]">
                <details class="reading-disclosure"><summary>查看独立 MACD 依据</summary><div class="audit-evidence-body">
                  <EvidenceReading :lines="divergenceEvidence(item)" />
                  <button v-if="divergenceFocus(item, bars.length, '')" :disabled="busy" @click="emit('locateDivergence', item)">定位比较区间</button>
                <div class="event-replays"><ConfirmationReplay :index="item.confirmed_index" :total="total" :busy="busy" label="MACD M1 提示" caption="提示确认" @seek="emit('seek', $event)" /></div>
                </div></details>
              </ResearchEventRecord>
              </div>
            </details>
            </template>
            <template #diagnostics="{ items, count: matchCount }">
            <details v-if="matchCount" class="wave-diagnostics research-panel research-hierarchy" open>
              <summary><strong>背离核验与规则对照</strong><span>{{ matchCount }} 组匹配 · 展示 {{ items.length }} 组</span></summary>
              <div class="research-panel-body">
              <dl class="audit-rule-guide">
                <div><dt>标准</dt><dd>使用有效 A</dd></div><div><dt>非标准</dt><dd>完整 A · 保留 DIF 改善、B/C 同侧与 B 回拉</dd></div>
                <div><dt>特殊</dt><dd>对照前一 A 的指标极值</dd></div><div><dt>双线</dt><dd>对照最近局部极值</dd></div>
              </dl>
              <p class="audit-history-note">各类分别记录依据，不互相覆盖。核验通过项数仅用于审核，不代表信号强弱或胜率。</p>
              <details v-for="(item, index) in items" :key="`${item.family}-${item.direction}-${item.c_start ?? item.dates.b_start}-${index}`" class="wave-diagnostic-row reading-disclosure">
                <summary>
                  <strong>{{ item.family === 'double' ? '双线' : item.family === 'special' ? '特殊' : item.family === 'nonstandard' ? '非标准' : '标准' }}{{ item.direction === 'down' ? '底' : '顶' }}背离</strong>
                  <span class="audit-status" :class="item.status">{{ evidenceStateLabels[diagnosticEvidenceState(item)] }}</span>
                  <span class="audit-period"><span>{{ item.family === 'double' ? structureDate(item.dates.c_start) : item.family === 'special' ? `B ${structureDate(item.dates.b_start)} — ${structureDate(item.dates.b_end)}` : `C ${structureDate(item.dates.c_start)} — ${structureDate(item.dates.c_end)}` }}</span><span class="audit-check-count">{{ item.checks.filter(check => check.passed).length }} / {{ item.checks.length }} 项通过</span></span>
                  <span v-if="item.status === 'blocked'" class="audit-failure">{{ waveFailureSummary(item) }}</span>
                </summary>
                <div class="audit-evidence-body">
                <p v-if="item.status === 'blocked' && item.first_candidate_index != null" class="audit-history-note">本段曾产生候选，当前检查未通过；历史状态见事件记录。</p>
                <EvidenceReading :lines="waveDiagnosticLines(item)" />
                <div v-if="item.comparisons?.length" class="wave-comparisons">
                  <p>以下保留旧版研究对照，不含此次新增的 B 价格限制；与当前三类标记独立。非标准标记完全不使用 DEA 容差。</p>
                  <details v-for="comparison in item.comparisons" :key="comparison.mode" class="reading-disclosure">
                    <summary>{{ waveComparisonName(comparison) }}<small>{{ comparison.passed ? (comparison.closed ? '结束复核通过 · 仅对照' : '暂时满足 · C 未结束') : '仍未通过' }}</small></summary>
                    <p v-if="!comparison.passed">{{ waveFailureSummary(comparison) }}</p>
                    <EvidenceReading :lines="waveComparisonLines(comparison)" />
                  </details>
                </div>
                </div>
              </details>
              </div>
            </details>
            </template>
            <template #events="{ items, count: matchCount }">
            <details v-if="matchCount" class="divergence-records research-panel research-hierarchy" open>
              <summary><strong>背离事件记录</strong><span>{{ matchCount }} 条匹配 · 展示 {{ items.length }} 条</span></summary>
              <div class="research-panel-body">
                <p class="event-scope-note">候选、已确认与失效分别保留；极值出现不代表当时已经确认。</p>
            <ResearchEventRecord v-for="(bc, index) in items" :key="`${bc.type}-${bc.curr_date}-${index}`" class="divergence-record"
              :title="divergenceName(bc)" :date="bc.curr_date" :tone="bc.type === 'macd_wave_nonstandard' ? 'nonstandard' : bc.direction === 'up' ? 'top' : 'bottom'"
              :state="eventEvidenceState(bc)" :state-label="evidenceStateLabels[eventEvidenceState(bc)]"
              :metadata="[{label:'对照日期',value:structureDate(bc.prev_date)}, {label:bc.status === 'superseded' ? '失效 / 替代日期' : bc.status === 'candidate' ? '首次提示' : '确认日期',value:structureDate(bc.status === 'superseded' ? bc.invalidated_date : bc.status === 'candidate' ? bc.detected_date : bc.confirmed_date)}]"
              :note="bc.status === 'candidate' && bc.preliminary_date ? '曾满足初步条件 · 等待走势完成' : undefined" :description="formatMessage(bc.msg)">
              <details class="divergence-evidence reading-disclosure">
                <summary>查看判定依据</summary>
                <div class="audit-evidence-body">
                <EvidenceReading :lines="divergenceEvidence(bc)" />
                <div class="divergence-locate-actions">
                <button v-if="divergenceFocus(bc, bars.length, '')" :disabled="busy" @click="emit('locateDivergence', bc)">{{ bc.type === 'macd' ? '定位前后极值' : '定位比较区间' }}</button>
                <button v-if="reversePenFocus(bc, bars.length, '')" :disabled="busy" @click="emit('locateReversePen', bc)">查看局部确认用笔</button>
                </div>
                <div class="event-replays">
                <ConfirmationReplay :index="bc.detected_index" :total="total" :busy="busy" :label="divergenceName(bc)" phase="首次提示" caption="首次提示" @seek="emit('seek', $event)" />
                <ConfirmationReplay v-if="bc.status === 'confirmed'" :index="bc.confirmed_index" :total="total" :busy="busy" :label="divergenceName(bc)" caption="最终确认" @seek="emit('seek', $event)" />
                <ConfirmationReplay v-if="bc.status === 'superseded'" :index="bc.invalidated_index" :total="total" :busy="busy" :label="divergenceName(bc)" phase="失效" caption="失效 / 替代" @seek="emit('seek', $event)" />
                <ConfirmationReplay v-if="bc.evidence?.replacement_detected_index != null" :index="bc.evidence.replacement_detected_index" :total="total" :busy="busy" label="后续替代候选" phase="首次提示" caption="后续替代候选" @seek="emit('seek', $event)" />
                </div>
                </div>
              </details>
            </ResearchEventRecord>
              </div>
            </details>
            </template>
            </SignalEvidenceBrowser>
  </div>
</template>
<style scoped>
.divergence-workspace, .signal-workspace { min-width: 0; }
.audit-status { display: inline-flex; align-items: center; gap: 6px; color: #a1abba; font-size: 10px; line-height: 1.8; font-weight: 400; }
.audit-status::before { content: ''; width: 4px; height: 4px; flex: 0 0 4px; border: 1px solid currentColor; border-radius: 50%; }
.audit-status.confirmed { color: #a7c6b7; }
.audit-status.confirmed::before { background: currentColor; }
.audit-status.candidate { color: #cbb38b; }
.audit-history-note, .wave-comparisons > p { color: var(--text-muted); font-size: 11px; line-height: 1.9; overflow-wrap: anywhere; text-align: justify; text-align-last: left; margin: 10px 0; }
.divergence-workspace .audit-evidence-body { padding-bottom: 12px; }
.divergence-locate-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.divergence-locate-actions:empty { display: none; }
.divergence-workspace .divergence-locate-actions button { min-height: 30px; font-size: 11px; padding: 5px 10px; background: rgba(255,255,255,.025); box-shadow: none; }
.wave-diagnostic-row { padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,.055); }
.wave-diagnostic-row:last-child { border-bottom: 0; }
.signal-workspace .wave-diagnostics .wave-diagnostic-row > summary { display: grid; grid-template-columns: minmax(0,1fr) auto 10px; align-items: baseline; gap: 6px 14px; padding: 12px 0; }
.wave-diagnostic-row > summary > strong { color: var(--text); font-size: 12px; font-weight: 500; }
.wave-diagnostics .wave-diagnostic-row > summary::before { content: none; }
.wave-diagnostic-row > summary::after { content: ''; grid-column: 3; grid-row: 1; width: 5px; height: 5px; border-right: 1px solid #91a2bb; border-bottom: 1px solid #91a2bb; transform: rotate(-45deg); transition: transform 150ms ease; }
.wave-diagnostic-row[open] > summary::after { transform: rotate(45deg); }
.audit-period { grid-column: 1 / 3; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 4px 16px; color: #8e9cad; font-size: 10px; line-height: 1.8; font-variant-numeric: tabular-nums; }
.audit-check-count { color: #a3adbc; white-space: nowrap; }
.audit-rule-guide { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 28px; margin: 8px 0 12px; }
.audit-rule-guide > div { display: grid; grid-template-columns: 44px minmax(0,1fr); gap: 10px; padding: 12px 0; border-bottom: 1px solid rgba(255,255,255,.045); font-size: 11px; line-height: 1.8; }
.audit-rule-guide dt { color: #bcc9d9; }
.audit-rule-guide dd { margin: 0; color: #97a5b8; }
.audit-failure { grid-column: 1 / 3; color: #b7a58c; font-size: 11px; line-height: 1.8; }
.wave-comparisons { margin-top: 16px; border-top: 1px solid rgba(255,255,255,.05); padding-top: 8px; }
.wave-comparisons > details > summary small { display: block; font-size: 10px; color: var(--text-muted); }
@container (max-width: 400px) {
  .audit-rule-guide { grid-template-columns: minmax(0,1fr); }
  .signal-workspace .wave-diagnostics .wave-diagnostic-row > summary { grid-template-columns: minmax(0,1fr) 10px; }
  .wave-diagnostic-row > summary::after { grid-column: 2; }
  .wave-diagnostic-row > summary > .audit-status { grid-column: 1; grid-row: 2; }
  .audit-period, .audit-failure { grid-column: 1; }
}
@media (prefers-reduced-motion: reduce) { .wave-diagnostic-row > summary::after { transition: none; } }
.wave-comparisons details { margin: 10px 0; }
</style>
