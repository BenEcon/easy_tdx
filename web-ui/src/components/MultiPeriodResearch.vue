<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import CloudResearchArchives from './CloudResearchArchives.vue'
import type { ArchiveDraft } from '../cloud-archives'
import { fetchResearchSnapshot, formatError, type BarSnapshot } from '../api'
import { targetIdentity, type ResearchTarget } from '../chanlun-target'
import { detectMarket } from '../market'
import { useAuth } from '../auth'
import { assertMarketData } from '../market-data-contract'
import { queryAction } from '../query-origin'
import type { RadarArchiveSource } from '../radar-archive'
import { detachStudyValue, freezeStudyContext, finishStudyArchive, type StudyArchivePayload } from '../study-archive'
import type { AdjustMode, Category } from '../types'
import NumberStepper from './NumberStepper.vue'
import MacSelect from './MacSelect.vue'
import ResearchContextDetails from './ResearchContextDetails.vue'
import MultiPeriodOverviewTable from './MultiPeriodOverviewTable.vue'
import { overviewPeriods } from '../period-overview'
import { canAutoStudy } from '../research-workspace'
import { studyPeriods as periods, studyLabel as label, studyNumber as fmt, studyWindowError, studyTime, type Study, type StudyPeriod as Period } from '../research-study'

const props = withDefaults(defineProps<{ code: string; target?: ResearchTarget; adjust: AdjustMode; asOf: string; busy?: boolean; primaryCategory: Category; primarySnapshot: BarSnapshot; maPeriods?: number[]; active?: boolean; radarSource?:RadarArchiveSource|null }>(), {active:true})
const {currentUser}=useAuth()
const selected = ref<Period[]>([...overviewPeriods])
const automatic = ref(true)
const selectedPeriods = computed(() => periods.filter(p => selected.value.includes(p.value)).map(p => p.value))
const volumeMultiple = ref(2)
const squeezePercent = ref(20)
const windowMode = ref('20')
const windowBars = ref(20)
const windowStart = ref('')
const windowEnd = ref('')
const maResearch = computed(() => [...new Set(props.maPeriods ?? [5,10,20,30,60,120,250])].sort((a,b)=>a-b))
const windowOptions = [{ value:'20',label:'最近 20 根' },{ value:'60',label:'最近 60 根' },{ value:'120',label:'最近 120 根' },{ value:'custom',label:'自定义根数' },{ value:'range',label:'指定时间区间' }]
const windowError = computed(() => studyWindowError(windowMode.value, windowStart.value, windowEnd.value, props.asOf))
watch(windowMode, mode => { if (mode === 'range' && !windowEnd.value) windowEnd.value = props.asOf.replace(' ', 'T').slice(0,16) })
const study = ref<Study | null>(null)
const loading = ref(false)
const errors = ref<string[]>([])
const periodErrors = ref<Record<string, string>>({})
const completed = shallowRef<{payload:StudyArchivePayload;settings:string;owner:string}|null>(null)
const settingsKey = computed(() => JSON.stringify([props.code, props.target, props.adjust, props.asOf, props.primaryCategory, props.primarySnapshot, props.radarSource, selected.value, volumeMultiple.value, squeezePercent.value, maResearch.value, windowMode.value, windowBars.value, windowStart.value, windowEnd.value]))
let generation = 0
let controller: AbortController | null = null
let scheduled: ReturnType<typeof setTimeout> | undefined
function cancel() { generation++; controller?.abort(); clearTimeout(scheduled); loading.value = false }
function schedule() {
  clearTimeout(scheduled)
  if (currentUser.value?.id && canAutoStudy(props.active,automatic.value,!!props.busy,props.asOf,selected.value.length,windowError.value)) scheduled = setTimeout(() => void run(), 500)
}
watch([settingsKey, () => props.busy], () => {
  cancel(); study.value = null; completed.value = null; errors.value = []; periodErrors.value = {}; schedule()
}, { immediate: true, flush:'sync' })
watch(()=>currentUser.value?.id,()=>{cancel();study.value=null;completed.value=null;errors.value=[];periodErrors.value={}}, {flush:'sync'})
watch(automatic, () => { if (automatic.value && !study.value) schedule(); else clearTimeout(scheduled) })
watch(() => props.active, active => { if (!active) cancel(); else if (!study.value) schedule() })
onBeforeUnmount(cancel)
const goodRows = computed(() => study.value?.rows.filter(r => !r.error) ?? [])
const detailElements = new Map<string, HTMLDetailsElement>()
function registerDetail(category: string, element: unknown) {
  if (element instanceof HTMLDetailsElement) detailElements.set(category, element)
  else detailElements.delete(category)
}
async function inspectPeriod(category: Period) {
  const element = detailElements.get(category)
  if (!element) return
  element.open = true
  await nextTick()
  element.scrollIntoView({ block: 'start' })
  element.querySelector('summary')?.focus({ preventScroll: true })
}

async function run(manual = false) {
  const owner=currentUser.value?.id??''
  if (!owner || !props.active || windowError.value || props.busy || !props.asOf || !selected.value.length) return
  clearTimeout(scheduled)
  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  const version = ++generation
  const settings=settingsKey.value
  const query=queryAction(manual)
  const identity = { code: props.code, adjust: props.adjust, asOf: props.asOf }
  const instrument: ResearchTarget = props.target ? {...props.target} : {kind:'stock',code:props.code,market:detectMarket(props.code)}
  const options = { volume_multiple: volumeMultiple.value, squeeze_quantile: squeezePercent.value / 100,
    ma_periods: maResearch.value, window_bars: windowMode.value === 'custom' ? windowBars.value : Number(windowMode.value) || 20,
    ...(windowMode.value === 'range' ? {window_start:windowStart.value, window_end:windowEnd.value} : {}) }
  study.value = null; completed.value = null; errors.value = []; periodErrors.value = {}; loading.value = true
  const snapshots: Array<{ category: Period; snapshot: BarSnapshot }> = []
  const failures:Record<string,string> = {}
  let context:ReturnType<typeof freezeStudyContext>|null=null
  const valid=()=>version===generation&&owner===currentUser.value?.id&&settings===settingsKey.value
  function accept(response:Study|null,problem='') {
    if(!valid()||!context)return
    const payload=finishStudyArchive(context,snapshots,failures,response,problem)
    completed.value={payload,settings,owner};study.value=payload.result
    periodErrors.value=Object.fromEntries(payload.result.rows.filter(row=>row.error).map(row=>[row.category,row.error!]))
    errors.value=payload.result.rows.filter(row=>row.error).map(row=>`${label(row.category)}：${row.error}`)
  }
  try {
    context=freezeStudyContext({code:identity.code,instrument,adjust:identity.adjust,as_of:windowMode.value==='range'?studyTime(windowEnd.value):identity.asOf,
      selected:[...selectedPeriods.value],primary:{category:props.primaryCategory,snapshot:props.primarySnapshot},
      parameters:{macd:[12,26,9],boll:[20,2],...options,window_start:options.window_start?studyTime(options.window_start):null,window_end:options.window_end?studyTime(options.window_end):null},
      ...(props.radarSource?{radarSource:props.radarSource}:{})})
    // Bounded sequential requests avoid flooding the shared quote connection.
    for (const category of context.selected) {
      if (!valid()) return
      try {
        const snapshot = category === context.primary.category ? context.primary.snapshot
          : await query(()=>fetchResearchSnapshot(instrument, category, 800, identity.adjust, signal))
        assertMarketData(snapshot.metadata,identity.adjust)
        if(snapshot.metadata.category!==category)throw new Error('返回行情周期与请求不一致，已排除该周期')
        if (!snapshot.bars.length) throw new Error('暂无行情')
        snapshots.push({ category, snapshot:detachStudyValue(snapshot) })
      } catch (error) {
        if (!valid()) return
        const message = formatError(error)
        failures[category]=message
        periodErrors.value[category] = message
      }
    }
    if (!valid()) return
    if (!snapshots.length) {accept(null);return}
    const response = await fetch('/api/v1/chanlun/observations', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Query-Origin': manual === true ? 'user' : 'system' }, signal,
      body: JSON.stringify({ as_of: identity.asOf, ...options,
        series: snapshots.map(({ category, snapshot }) => ({ category, code: targetIdentity(instrument), bars: snapshot.bars, bar_time: snapshot.metadata.bar_time ?? 'start' })),
      }),
    })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : `研究接口返回 ${response.status}，请检查区间和参数`)
    }
    const next = await response.json() as Study
    if (!valid()) return
    if (!Array.isArray(next?.rows)) throw new Error('研究接口未返回有效的周期结果，请重试')
    accept(next)
  } catch (error) {
    if (valid()) {
      const message = formatError(error)
      if(context)accept(null,message)
      else errors.value.push(message)
    }
  }
  finally { if (version === generation) loading.value = false }
}

function captureStudy() {
  if (!completed.value || loading.value || props.busy || completed.value.settings!==settingsKey.value || completed.value.owner!==currentUser.value?.id) throw new Error('研究尚未完成或上下文已变化，请完成后保存')
  return detachStudyValue(completed.value.payload)
}
function captureCloud(): ArchiveDraft {
  const snapshot=captureStudy()
  return {kind:'study',name:`${props.code} · 多周期研究 · ${snapshot.as_of}`.slice(0,120),note:'',payload:snapshot}
}
function exportSnapshot() {
  if (!study.value) return
  try {
  const snapshot=captureStudy()
  const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a'); anchor.href = url
  anchor.download = `${props.code}-缠论研究-${study.value.as_of.replace(/[: ]/g, '-')}.json`
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }catch(error){errors.value.push(formatError(error))}
}
</script>

<template>
  <details class="multi-study research-panel research-hierarchy" open>
    <summary><strong>多周期概览 · {{ code }}</strong><span>量价、动能、严格笔与背离</span></summary>
    <div class="research-panel-body">
    <div class="overview-actions">
      <div><span>共同截止</span><time>{{ study?.as_of || (windowMode === 'range' ? windowEnd.replace('T', ' ') : asOf) || '请先查询标的' }}</time></div>
      <label><input v-model="automatic" type="checkbox">自动更新</label>
      <button :disabled="loading || busy || !selected.length || !asOf || !!windowError" @click="run(true)">{{ loading ? '逐周期核验中…' : '更新概览' }}</button>
      <button :disabled="!study || loading" @click="exportSnapshot">保存研究快照</button>
    </div>
    <MultiPeriodOverviewTable :periods="selectedPeriods" :rows="study?.rows ?? []" :errors="periodErrors" :loading="loading" @inspect="inspectPeriod" />
    <p v-if="completed" class="study-policy">本次选定 {{ completed.payload.collection.selected_periods.length }} 个周期，{{ goodRows.length }} 个取得研究结果；未完成周期的具体原因一并保存。{{ completed.payload.radarSource ? '原雷达扫描来源独立封存，其他周期属于本次另行研究，不代表原扫描结果。' : '' }}</p>
    <CloudResearchArchives :capture="captureCloud" :busy="!study || loading || !!busy" />
    <details class="overview-settings reading-disclosure"><summary>周期与研究参数</summary>
    <div class="study-tools">
      <div class="study-window">
        <label class="study-window-label"><span>研究窗口</span><MacSelect v-model="windowMode" :options="windowOptions" aria-label="研究窗口" /></label>
        <label v-if="windowMode === 'custom'"><span>已收盘根数</span><NumberStepper v-model="windowBars" :min="3" :max="800" :step="1" aria-label="研究窗口根数" /></label>
        <template v-if="windowMode === 'range'"><label><span>从</span><input v-model="windowStart" type="datetime-local" aria-label="研究开始时间" :max="windowEnd || asOf.replace(' ','T').slice(0,16)"></label><label><span>至</span><input v-model="windowEnd" type="datetime-local" aria-label="研究结束时间" :min="windowStart" :max="asOf.replace(' ','T').slice(0,16)"></label></template>
        <p>限定近期统计与事件追踪范围；指标继续使用窗口前历史预热。每个周期下方列出实际覆盖时间。</p>
        <p v-if="windowError" class="study-error" role="alert">{{ windowError }}</p>
      </div>
      <fieldset class="study-periods">
        <legend>观察周期 <span>已选 {{ selected.length }} 个</span></legend>
        <label v-for="period in periods" :key="period.value" :class="{ selected: selected.includes(period.value) }">
          <input v-model="selected" type="checkbox" :value="period.value">
          <span class="period-check" aria-hidden="true">✓</span><span>{{ period.label }}</span>
        </label>
      </fieldset>
      <div class="study-controls">
        <div class="study-parameters">
          <label><span>放量阈值</span><NumberStepper v-model="volumeMultiple" aria-label="放量阈值" :min="1" :max="10" :step=".25" compact /><span class="parameter-unit">倍</span></label>
          <label><span>收口分位</span><NumberStepper v-model="squeezePercent" aria-label="收口分位" :min="1" :max="99" :step="1" compact /><span class="parameter-unit">%</span></label>
        </div>
      </div>
      <div class="study-context"><span>研究截止</span><time>{{ study?.as_of || (windowMode === 'range' ? windowEnd.replace('T', ' ') : asOf) || '请先查询标的' }}</time><span>仅使用已收盘 K 线</span></div>
      <details class="study-method reading-disclosure">
        <summary>计算口径与参数说明</summary>
        <dl class="research-copy">
          <div><dt>数据范围</dt><dd>只使用共同截止前的完整 K 线，未收盘柱不参与本表。</dd></div>
          <div><dt>快照与预热</dt><dd>主图周期复用原快照和预热起点，不重复拉取。</dd></div>
          <div><dt>指标参数</dt><dd><dl class="parameter-reference"><div><dt>排列 MA</dt><dd>{{ maResearch.join(' / ') }}</dd></div><div><dt>固定快慢组</dt><dd>MA5 / MA10 · MAVOL5 / MAVOL10</dd></div><div><dt>MACD</dt><dd>12 / 26 / 9</dd></div><div><dt>BOLL</dt><dd>20 / 2</dd></div></dl></dd></div>
          <div><dt>显隐与参数</dt><dd>排列研究采用左侧全部均线的实际周期，隐藏曲线不改变研究结论。开启自动更新后，修改参数将重新核验；关闭时点击更新概览。</dd></div>
          <div><dt>修复过程</dt><dd>允许不同根先后改善；反向变化会中断原事件，窗口外事件不拼接为当前配合。全部是观察，不生成正式买卖点。</dd></div>
          <div><dt>对照窗口</dt><dd>成交量对照前 <strong>20 根</strong>；收口对照此前最多 <strong>120 根</strong>带宽分位。</dd></div>
        </dl>
        <p class="research-caveat"><strong>使用边界</strong><span>阈值是研究设置，并非已验证胜率。</span></p>
      </details>
    </div>
    </details>
    <p v-for="error in errors" :key="error" class="study-error" role="alert">{{ error }}</p>
    <p v-if="!study && !errors.length" class="study-empty" role="status">{{ loading ? '正在按共同截止时间核验所选周期…' : '选择观察周期，更新后查看量价、动能与结构对照。' }}</p>
    <div v-if="goodRows.length" class="study-results">
      <div class="study-results-heading"><h4>周期观察</h4><span>点击周期展开过程与依据</span></div>
      <details v-for="row in goodRows" :key="row.category" :ref="el => registerDetail(row.category, el)" class="study-period-detail">
        <summary><span class="study-period-name">{{ label(row.category) }}</span><div><strong>{{ row.recent.overall }} · {{ row.recent.tail }}</strong><small>{{ row.direction_observation.description }}</small></div><span class="study-period-price">{{ fmt(row.price) }}<small>{{ row.axis }}</small></span></summary>
        <div class="study-row-range"><span>研究窗口 {{ row.window.start }} — {{ row.window.end }}</span><span>{{ row.window.count }} 根 · 已收盘截止 {{ row.last_closed_at }}</span><span v-if="row.window.truncated || row.warmup_warning">{{ row.window.truncated ? '窗口覆盖不足 · ' : '' }}{{ row.warmup_warning ? 'EMA 预热不足 120 根' : '' }}</span></div>
        <ResearchContextDetails :row="row" />
      </details>
      <details class="study-axis reading-disclosure"><summary>跨周期过轴时间对照</summary>
        <p>区分窗口内首次、最近一次与当前状态；“未观察到”不等于历史从未发生。不设小周期必须先过轴的门槛。</p>
        <div class="study-scroll" tabindex="0" aria-label="跨周期过轴时间对照，可横向滚动"><table><thead><tr><th>周期 / 线</th><th>窗口内首次上轴</th><th>最近上轴</th><th>最近上轴后失效</th><th>当前</th></tr></thead><tbody>
          <template v-for="row in goodRows" :key="row.category"><tr v-for="axis in row.axis_history" :key="axis.key"><th>{{ label(row.category) }} · {{ axis.key === 'both_axis' ? '双线共同' : axis.key }}</th><td>{{ axis.first_up ?? '未观察到' }}</td><td>{{ axis.last_up ?? '未观察到' }}</td><td>{{ axis.invalidated_at ?? '无失效记录' }}</td><td>{{ axis.currently_above ? '轴上' : '未在轴上' }}</td></tr></template>
        </tbody></table></div>
      </details>
    </div>
    <div v-if="study" class="study-notes">
      <h4>观察与分歧</h4>
      <p v-for="conflict in study.conflicts" :key="conflict" class="study-conflict">{{ conflict }}</p>
      <p class="study-policy">{{ study.policy }}。当前调整后快照不等于历史当天的数据版本；缺失的旧分钟行情不作推断。</p>
    </div>
    </div>
  </details>
</template>

<style scoped>
.overview-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px 14px;margin-top:10px}.overview-actions>div{display:flex;align-items:baseline;flex-wrap:wrap;gap:6px 10px;margin-right:auto;font-size:11px;color:var(--text-muted)}.overview-actions time{font-variant-numeric:tabular-nums;color:var(--text-dim)}.overview-actions label{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--text-muted);white-space:nowrap}.overview-actions input{appearance:auto;width:13px;height:13px;min-height:13px;margin:0;accent-color:var(--accent)}.overview-actions button{font-size:11px;min-height:32px;padding:6px 10px}.overview-settings{margin-bottom:18px}.study-period-detail{scroll-margin-top:85px}
.study-window{display:flex;align-items:center;flex-wrap:wrap;gap:12px 18px;padding:0 0 18px;margin-bottom:18px;border-bottom:1px solid var(--border)}.study-window-label{gap:12px!important}.study-window :deep(.mac-select){min-width:156px}.study-window>p{flex-basis:100%;margin:0!important}.study-window input[type=datetime-local]{color-scheme:dark;border:1px solid var(--border);border-radius:7px;background:var(--bg-input,rgba(255,255,255,.035));color:var(--text);font:inherit;padding:7px;min-width:0}.study-results-heading{display:flex;align-items:center;justify-content:space-between;margin:18px 0 12px}.study-results-heading h4{font-size:13px;margin:0}.study-results-heading span{font-size:11px;color:var(--text-muted)}.study-period-detail{border-top:1px solid var(--border);margin:0}.study-period-detail>summary{display:grid;grid-template-columns:68px minmax(0,1fr) auto;gap:16px;align-items:center;padding:17px 10px;list-style:none;border-radius:8px;transition:background .16s ease}.study-period-detail>summary::-webkit-details-marker{display:none}.study-period-detail>summary:hover{background:rgba(255,255,255,.025)}.study-period-detail>summary .study-period-name{margin:0;font-size:13px;color:var(--text);font-weight:600}.study-period-name::before{content:'›';display:inline-block;width:15px;color:var(--text-muted);transition:transform .16s}.study-period-detail[open]>summary .study-period-name::before{transform:rotate(90deg)}.study-period-detail>summary strong{font-size:12px;font-weight:500}.study-period-detail>summary .study-period-price{text-align:right;color:var(--text);font-size:14px;font-variant-numeric:tabular-nums}.study-row-range{display:flex;flex-wrap:wrap;gap:6px 20px;margin:0 18px;padding:4px 0 14px;border-bottom:1px solid var(--border);font-size:11px;color:var(--text-muted)}.study-axis{margin-top:20px}.study-axis>p{font-size:12px;line-height:1.7;color:var(--text-muted)}@media(max-width:600px){.study-window{align-items:flex-start}.study-window label{max-width:100%}.study-period-detail>summary{grid-template-columns:55px minmax(0,1fr);gap:10px}.study-period-detail>summary .study-period-price{grid-column:2;text-align:left;margin:0}.study-results-heading{align-items:flex-start;gap:12px}.study-results-heading span{text-align:right}.study-row-range{margin:0 12px}.study-window input[type=datetime-local]{max-width:220px}}@media(prefers-reduced-motion:reduce){.study-period-detail>summary,.study-period-name::before{transition:none}}
.study-tools label{white-space:nowrap;flex-shrink:0}.study-tools input[type=checkbox]{appearance:auto;width:14px;height:14px;min-height:14px;padding:0;margin:0;flex:0 0 14px}.study-controls :deep(.number-stepper){width:80px;flex:0 0 80px}.study-controls>button{white-space:nowrap}
.multi-study{margin:14px 0;border-top:1px solid var(--border);padding-top:12px;color:var(--text)}
summary{cursor:pointer;font-size:13px;font-weight:600}summary span{margin-left:12px;color:var(--text-muted);font-size:11px;font-weight:400}
.study-tools{padding:14px 0}.study-tools fieldset{display:flex;flex-wrap:wrap;gap:12px;border:0;padding:0;margin:0 0 12px}.study-tools legend{font-size:11px;color:var(--text-muted);margin-bottom:8px}.study-tools label{display:inline-flex;align-items:center;gap:6px;font-size:12px}.study-tools input{accent-color:#559eee}.study-controls{display:flex;flex-wrap:wrap;align-items:center;gap:12px}.study-controls button{padding:6px 11px;border:1px solid var(--border);border-radius:7px;background:rgba(255,255,255,.04);color:var(--text);font-size:12px}.study-controls button:disabled{opacity:.45}.study-tools p,.study-notes p{margin:9px 0;color:var(--text-muted);font-size:11px;line-height:1.6}.study-error{color:#e6af81;font-size:12px}.study-scroll{max-width:100%;overflow:auto}table{width:100%;min-width:880px;border-collapse:collapse;font-size:12px}th,td{text-align:left;vertical-align:top;padding:11px 12px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}thead th{font-size:11px;color:var(--text-muted);font-weight:500}tbody th{font-weight:500;white-space:nowrap}small{display:block;color:var(--text-muted);font-size:10px;line-height:1.65;margin-top:4px}.study-notes{padding-top:8px}@media(max-width:760px){summary span{display:block;margin:5px 0}.study-controls{align-items:flex-start}.study-controls label{font-size:11px}th,td{padding:9px}}
</style>
