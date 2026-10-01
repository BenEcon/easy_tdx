<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchBarSnapshot, formatError, type BarSnapshot } from '../api'
import { detectMarket } from '../market'
import { compactNumber } from '../technical-indicators'
import type { AdjustMode, Category } from '../types'
import NumberStepper from './NumberStepper.vue'

const props = defineProps<{ code: string; adjust: AdjustMode; asOf: string; busy?: boolean; primaryCategory: Category; primarySnapshot: BarSnapshot }>()
type Period = Category | 'MIN_120'
const periods: Array<{ value: Period; label: string }> = [
  { value: 'WEEK', label: '周线' }, { value: 'DAY', label: '日线' },
  { value: 'MIN_120', label: '120 分钟' }, { value: 'MIN_60', label: '60 分钟' },
  { value: 'MIN_30', label: '30 分钟' }, { value: 'MIN_15', label: '15 分钟' },
  { value: 'MIN_5', label: '5 分钟' }, { value: 'MIN_1', label: '1 分钟' },
]
const label = (period: string) => periods.find(p => p.value === period)?.label ?? period
const selected = ref<Period[]>(['DAY', 'MIN_30', 'MIN_5'])
const volumeMultiple = ref(2)
const squeezePercent = ref(20)
type Pair = { state: string; fast: number | null; slow: number | null; fast_slope?: number; slow_slope?: number }
interface StudyRow {
  category: Period; error?: string; bar_count: number; last_date: string; price: number
  ma5: number | null; ma10: number | null; above_ma5: boolean | null; above_ma10: boolean | null
  pairs: { ma: Pair; volume: Pair; macd: Pair }; axis: string; histogram: string
  dif_toward_zero: boolean | null; dea_toward_zero: boolean | null
  observations: string[]; warmup_warning: boolean; excluded_bars: number
  divergences: Array<{ direction: string; status: string; date: string; confirmed_date: string | null }>
  structure: { confirmed_pens: number; segments: number; centres: number; state: string }
}
interface Study { as_of: string; rows: StudyRow[]; conflicts: string[]; policy: string; parameters: unknown; rule_version: string }
const study = ref<Study | null>(null)
const loading = ref(false)
const errors = ref<string[]>([])
const frozen = ref<Array<{ category: Period; snapshot: BarSnapshot }>>([])
const settingsKey = computed(() => JSON.stringify([props.code, props.adjust, props.asOf, props.primaryCategory, props.primarySnapshot, selected.value, volumeMultiple.value, squeezePercent.value]))
let generation = 0
watch(settingsKey, () => { generation++; study.value = null; frozen.value = []; errors.value = []; loading.value = false })
const fmt = (value: number | null | undefined) => value == null ? '—' : value.toFixed(2)
const volume = (value: number | null) => value == null ? '—' : compactNumber(value)
const relation = (price: number, average: number | null) => average == null ? '待预热' : price > average ? '上方' : price < average ? '下方' : '重合'
const signed = (value: number | undefined) => value == null ? '待预热' : value > 0 ? '↑' : value < 0 ? '↓' : '→'
const states: Record<string, string> = { none: '暂无中枢', active: '中枢延伸', departed: '已离开，待回试', exited: '离开回试已确认' }
const goodRows = computed(() => study.value?.rows.filter(r => !r.error) ?? [])

async function run() {
  const version = ++generation
  const identity = { code: props.code, adjust: props.adjust, asOf: props.asOf }
  const options = { volume_multiple: volumeMultiple.value, squeeze_quantile: squeezePercent.value / 100 }
  study.value = null; frozen.value = []; errors.value = []; loading.value = true
  const snapshots: Array<{ category: Period; snapshot: BarSnapshot }> = []
  const failures: string[] = []
  try {
    // Bounded sequential requests avoid flooding the shared quote connection.
    for (const { value: category } of periods.filter(p => selected.value.includes(p.value))) {
      if (version !== generation) return
      try {
        const snapshot = category === props.primaryCategory ? props.primarySnapshot
          : await fetchBarSnapshot(detectMarket(identity.code), identity.code, category, 800, identity.adjust)
        if (!snapshot.metadata || snapshot.metadata.actual_adjust !== identity.adjust) throw new Error('实际复权方式与选择不一致，已排除该周期')
        if (!snapshot.bars.length) throw new Error('暂无行情')
        snapshots.push({ category, snapshot })
      } catch (error) { failures.push(`${label(category)}：${formatError(error)}`) }
    }
    if (version !== generation) return
    errors.value = failures
    if (!snapshots.length) return
    const response = await fetch('/api/v1/chanlun/observations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ as_of: identity.asOf, ...options,
        series: snapshots.map(({ category, snapshot }) => ({ category, code: identity.code, bars: snapshot.bars })),
      }),
    })
    if (!response.ok) throw new Error(`研究接口返回 ${response.status}`)
    const next = await response.json() as Study
    if (version !== generation) return
    study.value = next; frozen.value = snapshots
    errors.value.push(...next.rows.filter(r => r.error).map(r => `${label(r.category)}：${r.error}`))
  } catch (error) { if (version === generation) errors.value.push(formatError(error)) }
  finally { if (version === generation) loading.value = false }
}

function exportSnapshot() {
  if (!study.value) return
  const snapshot = { format: 'chanlun-research-snapshot-v1', code: props.code, adjust: props.adjust,
    as_of: study.value.as_of, historical_data_vintage: false, result: study.value, series: frozen.value,
    primary: { category: props.primaryCategory, snapshot: props.primarySnapshot },
    warmup_policy: '各周期从所保存行情首根开始；EMA 首值为首根收盘价；计算不舍入' }
  const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a'); anchor.href = url
  anchor.download = `${props.code}-缠论研究-${study.value.as_of.replace(/[: ]/g, '-')}.json`
  anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
</script>

<template>
  <details class="multi-study">
    <summary>多周期研究 <span>量价与动能观察，不生成正式买卖点</span></summary>
    <div class="study-tools">
      <fieldset><legend>观察周期</legend><label v-for="period in periods" :key="period.value"><input v-model="selected" type="checkbox" :value="period.value">{{ period.label }}</label></fieldset>
      <div class="study-controls">
        <label>放量阈值 <NumberStepper v-model="volumeMultiple" aria-label="放量阈值" :min="1" :max="10" :step=".25" compact /> 倍</label>
        <label>收口分位 <NumberStepper v-model="squeezePercent" aria-label="收口分位" :min="1" :max="99" :step="1" compact /> %</label>
        <button :disabled="loading || busy || !selected.length || !asOf" @click="run">{{ loading ? '逐周期核验中…' : '更新研究' }}</button>
        <button :disabled="!study || loading" @click="exportSnapshot">保存研究快照</button>
      </div>
      <p>共同截止：{{ asOf || '请先查询股票' }} · 只使用此前完整 K 线；主图周期复用原快照和预热起点，不重复拉取。未收盘柱不参与本表。</p>
      <p>MA 5/10 · MAVOL 5/10 · MACD 12/26/9 · BOLL 20/2；成交量对照前 20 根，收口对照此前最多 120 根带宽分位。阈值是研究设置，并非已验证胜率。</p>
    </div>
    <p v-for="error in errors" :key="error" class="study-error" role="alert">{{ error }}</p>
    <div v-if="goodRows.length" class="study-scroll" tabindex="0" aria-label="多周期对照表，可横向滚动">
      <table>
        <thead><tr><th>周期 / 数据截止</th><th>价格 / 均线</th><th>成交量均线</th><th>MACD</th><th>背离 / 结构</th></tr></thead>
        <tbody><tr v-for="row in goodRows" :key="row.category">
          <th>{{ label(row.category) }}<small>{{ row.last_date }}</small><small>{{ row.bar_count }} 根<span v-if="row.warmup_warning"> · 预热不足</span></small></th>
          <td><strong>{{ fmt(row.price) }}</strong><small>MA5 {{ fmt(row.ma5) }} / MA10 {{ fmt(row.ma10) }}</small><small>价格在 MA5 {{ relation(row.price, row.ma5) }} / MA10 {{ relation(row.price, row.ma10) }}</small><small>{{ row.pairs.ma.state }} · 快 {{ signed(row.pairs.ma.fast_slope) }} 慢 {{ signed(row.pairs.ma.slow_slope) }}</small></td>
          <td>{{ row.pairs.volume.state }}<small>快 {{ signed(row.pairs.volume.fast_slope) }} 慢 {{ signed(row.pairs.volume.slow_slope) }}</small><small>MAVOL5 {{ volume(row.pairs.volume.fast) }}<br>MAVOL10 {{ volume(row.pairs.volume.slow) }}</small></td>
          <td>{{ row.axis }} · {{ row.pairs.macd.state }}<small>{{ row.histogram }} · DIF {{ signed(row.pairs.macd.fast_slope) }} DEA {{ signed(row.pairs.macd.slow_slope) }}</small><small>DIF {{ row.dif_toward_zero ? '靠近零轴' : '未靠近零轴' }} / DEA {{ row.dea_toward_zero ? '靠近零轴' : '未靠近零轴' }}</small></td>
          <td>{{ states[row.structure.state] ?? row.structure.state }}<small>{{ row.structure.confirmed_pens }} 确认笔 / {{ row.structure.segments }} 线段 / {{ row.structure.centres }} 中枢</small><small v-for="(event, i) in row.divergences" :key="i">{{ event.date }} · {{ event.direction === 'up' ? '顶' : '底' }}背离 · {{ event.status === 'candidate' ? '候选' : '已确认' }}</small><small v-if="!row.divergences.length">暂无有效背离记录</small></td>
        </tr></tbody>
      </table>
    </div>
    <div v-if="study" class="study-notes">
      <p v-for="conflict in study.conflicts" :key="conflict">{{ conflict }}</p>
      <template v-for="row in goodRows" :key="row.category"><p v-for="note in row.observations" :key="note"><strong>{{ label(row.category) }}</strong> · {{ note }}</p></template>
      <p>{{ study.policy }}。当前调整后快照不等于历史当天的数据版本；缺失的旧分钟行情不作推断。</p>
    </div>
  </details>
</template>

<style scoped>
.study-tools label{white-space:nowrap;flex-shrink:0}.study-tools input[type=checkbox]{appearance:auto;width:14px;height:14px;min-height:14px;padding:0;margin:0;flex:0 0 14px}.study-controls :deep(.number-stepper){width:80px;flex:0 0 80px}.study-controls>button{white-space:nowrap}
.multi-study{margin:14px 0;border-top:1px solid var(--border);padding-top:12px;color:var(--text)}
summary{cursor:pointer;font-size:13px;font-weight:600}summary span{margin-left:12px;color:var(--text-muted);font-size:11px;font-weight:400}
.study-tools{padding:14px 0}.study-tools fieldset{display:flex;flex-wrap:wrap;gap:12px;border:0;padding:0;margin:0 0 12px}.study-tools legend{font-size:11px;color:var(--text-muted);margin-bottom:8px}.study-tools label{display:inline-flex;align-items:center;gap:6px;font-size:12px}.study-tools input{accent-color:#559eee}.study-controls{display:flex;flex-wrap:wrap;align-items:center;gap:12px}.study-controls button{padding:6px 11px;border:1px solid var(--border);border-radius:7px;background:rgba(255,255,255,.04);color:var(--text);font-size:12px}.study-controls button:disabled{opacity:.45}.study-tools p,.study-notes p{margin:9px 0;color:var(--text-muted);font-size:11px;line-height:1.6}.study-error{color:#e6af81;font-size:12px}.study-scroll{max-width:100%;overflow:auto}table{width:100%;min-width:880px;border-collapse:collapse;font-size:12px}th,td{text-align:left;vertical-align:top;padding:11px 12px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}thead th{font-size:11px;color:var(--text-muted);font-weight:500}tbody th{font-weight:500;white-space:nowrap}small{display:block;color:var(--text-muted);font-size:10px;line-height:1.65;margin-top:4px}.study-notes{padding-top:8px}@media(max-width:760px){summary span{display:block;margin:5px 0}.study-controls{align-items:flex-start}.study-controls label{font-size:11px}th,td{padding:9px}}
</style>
