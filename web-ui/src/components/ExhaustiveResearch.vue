<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { Bar, Category } from '../types'
import { replayExhaustive, replayCandidateAudit, formatError } from '../api'
import { validSearchPage, validAudit, reasons, gates, detailText, type SearchPage, type CandidateAudit } from '../exhaustive-research'
import ReleasedRecursionInspector from './ReleasedRecursionInspector.vue'
const props = defineProps<{code: string; category: Category; bars: Bar[]; total: number; busy: boolean; structureSettings?: import('../structure-settings').StructureSettings}>()
const emit = defineEmits<{seek: [position: number]}>()
const page = ref<SearchPage | null>(null), audit = ref<CandidateAudit | null>(null)
const progress = ref({emitted: 0, complete: false})
const selectedIndex = ref(0), working = ref(false), error = ref(''), pageIndex = ref(0)
const checkpoints = ref<{cursor: string | null; before: number}[]>([{cursor: null, before: 0}])
let generation = 0, controller: AbortController | undefined, auditToken: string | undefined
const selected = computed(() => page.value?.results[selectedIndex.value])
function stop() { generation++; controller?.abort(); working.value = false }
function reset() { stop(); page.value = null; audit.value = null; progress.value = {emitted: 0, complete: false}; error.value = ''; checkpoints.value = [{cursor: null, before: 0}]; pageIndex.value = 0; selectedIndex.value = 0 }
watch(() => [props.code, props.category, props.bars, props.structureSettings], reset)
watch(() => props.busy, value => { if (value) stop() })
onBeforeUnmount(stop)
function request() { return {code: props.code, category: props.category, bars: props.bars, visible_count: props.bars.length, structure_settings: props.structureSettings} }
async function search(index: number, continuous = false) {
  if (working.value || props.busy || !props.bars.length) return
  const run = ++generation; controller = new AbortController(); working.value = true; error.value = ''; audit.value = null
  const req = request()
  try {
    do {
      const checkpoint = checkpoints.value[index]!
      const next = await replayExhaustive({...req, cursor: checkpoint.cursor, page_size: 2}, controller.signal)
      if (run !== generation) return
      if (!validSearchPage(next, req.visible_count, checkpoint.before, page.value?.fingerprint)) throw new Error('分解批次无法核验，未标记完成')
      page.value = next; pageIndex.value = index; selectedIndex.value = 0
      progress.value = {emitted: Math.max(progress.value.emitted, next.emitted), complete: progress.value.complete || next.complete}
      checkpoints.value.splice(index + 1)
      if (next.next_cursor) checkpoints.value.push({cursor: next.next_cursor, before: next.emitted})
      if (next.complete || !continuous) break
      index++
    } while (run === generation)
  } catch (e) { if (run === generation) error.value = formatError(e) }
  finally { if (run === generation) working.value = false }
}
function next(continuous = false) { search(page.value ? pageIndex.value + 1 : 0, continuous) }
async function trace(offset = 0, token?: string) {
  if (working.value || props.busy) return
  const run = ++generation; controller = new AbortController(); working.value = true; error.value = ''
  const req = request(); auditToken = token
  try {
    const value = await replayCandidateAudit({...req, offset, solution_token: token}, controller.signal)
    if (run !== generation) return
    if (!validAudit(value, req.visible_count, offset, page.value?.fingerprint)) throw new Error('判定记录无法核验')
    audit.value = value
  } catch (e) { if (run === generation) error.value = formatError(e) }
  finally { if (run === generation) working.value = false }
}
</script>
<template>
  <details class="exhaustive research-panel">
    <summary><strong>完整分解搜索与失败追踪</strong><span>固定工程规则 · 当前有限行情</span></summary>
    <div class="research-panel-body">
    <dl class="research-copy"><div><dt>搜索范围</dt><dd>固定当前笔、线段和中枢规则，穷举各层互不重叠的候选组合；每个分支重新计算高层、反向确认与归属。</dd></div><div><dt>使用边界</dt><dd>包含保留未完成来源的分解，不宣称覆盖原著所有解释，不用于交易。</dd></div></dl>
    <div class="actions">
      <button :disabled="busy || working || progress.complete" @click="next(true)">{{ page ? '继续穷举' : '开始穷举' }}</button>
      <button v-if="working" @click="stop">停止计算</button>
      <button :disabled="busy || working" @click="trace()">追踪默认分析</button>
      <button v-if="page" :disabled="working" @click="reset">重新开始</button>
      <span role="status">{{ progress.complete ? '穷举完成' : working ? '计算中 · 尚未完成' : page ? '已暂停 · 尚未完成' : '尚未开始' }}{{ page ? ` · 已枚举 ${progress.emitted} 个分解` : '' }}</span>
    </div>
    <p class="research-caveat"><strong>完成与续接</strong><span>组合数量可能指数增长；停止后可从已完成批次续接。只有待搜索分支全部耗尽才标记完成，服务器重启可能使检查点失效。</span></p>
    <p v-if="error" class="research-error" role="alert">{{ error }}</p>
    <section v-if="page">
      <div class="actions">
        <button :disabled="working || busy || pageIndex === 0" @click="search(0)">首批</button>
        <button :disabled="working || busy || pageIndex === 0" @click="search(pageIndex - 1)">上一批</button>
        <button :disabled="working || busy || page.complete" @click="next()">下一批</button>
        <button v-for="(result, i) in page.results" :key="result.id" :disabled="working || busy" :aria-pressed="selectedIndex === i" @click="selectedIndex = i; audit = null">分解 {{ result.ordinal }} · M{{ result.snapshot.highest_completed_level }}</button>
        <button :disabled="working || busy" @click="trace(0, selected?.solution_token)">追踪此分解</button>
      </div>
      <p v-if="selected">分解 {{ selected.ordinal }}：外部 {{ selected.snapshot.external_frontier_ids.length }} 条，未完成来源 {{ selected.snapshot.unresolved_segment_indices.length }} 条。此处回放重算默认分析，不把研究方案写入主图。</p>
      <ReleasedRecursionInspector v-if="selected" :data="selected.snapshot" :total="total" :busy="busy || working" :locatable="false" @seek="emit('seek', $event)" />
    </section>
    <section v-if="audit" class="audit">
      <h4>{{ audit.interpretation === 'default' ? '默认分析' : '所选分解' }} · 实际判定记录</h4>
      <p>已接纳 {{ audit.input.accepted_segment_count }} 条基础线段；扫描 {{ audit.total_attempts }} 个类型／起止窗口。相同来源的不同类型分别检查。</p>
      <p v-if="!audit.total_attempts">尚无可扫描的已确认基础结构，不能据此认定 MACD 条件失败。</p>
      <p v-for="(r, i) in audit.input.input_rejections" :key="i">输入第 {{ r.position + 1 }} 项：{{ reasons[r.reason] ?? r.reason }}。其后 {{ audit.input.rejected_suffix_count }} 项（含本项）未进入连续来源链，后续候选条件未检查。</p>
      <details class="reading-disclosure"><summary>原因汇总</summary><dl class="audit-reasons"><div v-for="(count, reason) in audit.summary" :key="reason"><dt>{{ reasons[reason] ?? reason }}</dt><dd>{{ count }}</dd></div></dl></details>
      <details v-if="audit.input.chain_boundaries.length"><summary>递归链断点 · {{ audit.input.chain_boundaries.length }} 处</summary><p v-for="(boundary, i) in audit.input.chain_boundaries" :key="i">M{{ boundary.level }} · 来源 {{ boundary.left_source + 1 }} → {{ boundary.right_source + 1 }}：{{ reasons[boundary.reason] ?? boundary.reason }}。所有跨此断点的候选窗口未评估。</p></details>
      <div class="attempts">
        <details v-for="(row, i) in audit.attempts" :key="audit.offset + i">
          <summary>M{{ row.level }} · {{ row.kind === 'trend' ? '趋势' : '盘整' }} · 来源 {{ row.source_first + 1 }}–{{ row.source_last + 1 }}<span>{{ reasons[row.reason ?? 'candidate_formed'] ?? row.reason }}</span></summary>
          <p v-if="row.selection">组合选择：{{ row.selection === 'selected' ? '本分支已选择' : '本分支未选择（不是规则失败）' }}</p>
          <p v-if="row.confirmed_index !== undefined">确认于第 {{ row.confirmed_index + 1 }} 根 K 线；可用时间与价格终点分别保留。</p>
          <p>{{ detailText(row.details) }}</p>
          <details><summary>MACD 与价格门槛 · {{ row.macd_checks.length }} 项已检查</summary>
            <p>未评估表示前置条件不足，不表示通过或失败。证据值最多显示六位小数，不参与判定舍入。</p>
            <div v-for="(label, key) in gates" :key="key" class="gate">
              <strong>{{ label }}：{{ row.macd_checks.find(g => g.gate === key)?.passed === true ? '通过' : row.macd_checks.find(g => g.gate === key)?.passed === false ? '未通过' : '未评估' }}</strong>
              <p v-if="row.macd_checks.find(g => g.gate === key)">{{ detailText(row.macd_checks.find(g => g.gate === key)!.values) }}</p>
            </div>
          </details>
        </details>
      </div>
      <div class="actions"><button :disabled="busy || working || audit.offset === 0" @click="trace(Math.max(0, audit.offset - 50), auditToken)">上一页记录</button><span>{{ audit.total_attempts ? audit.offset + 1 : 0 }}–{{ audit.offset + audit.attempts.length }} / {{ audit.total_attempts }}</span><button :disabled="busy || working || audit.next_offset === null" @click="trace(audit.next_offset!, auditToken)">下一页记录</button></div>
    </section>
    </div>
  </details>
</template>
<style scoped>
.exhaustive { border-top: 1px solid var(--border); margin-top: 12px; padding-top: 10px; min-width: 0; font-size: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.8; overflow-wrap: anywhere; }
summary span { color: var(--text-muted); margin-left: 12px; }
p { color: var(--text-muted); line-height: 1.8; margin: 8px 0; overflow-wrap: anywhere; }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 10px 0; }
button { min-height: 30px; padding: 4px 10px; font-size: 12px; transition: background-color .15s; }
button[aria-pressed=true] { border-color: var(--accent); background: rgba(74,158,255,.08); }
strong, h4 { font-weight: 550; }
.attempts { max-height: 520px; overflow: auto; }
.attempts > details, .gate { border-top: 1px solid var(--border); padding: 5px 0; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
@media (max-width: 560px) { summary span { display: block; margin-left: 0; } }
@media (prefers-reduced-motion: reduce) { button { transition: none; } }
</style>
