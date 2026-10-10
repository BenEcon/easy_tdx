<script setup lang="ts">
import { queryAction } from '../query-origin'
import { computed, ref, watch, onBeforeUnmount } from 'vue'

import MacSelect from './MacSelect.vue'
import AdjustPicker from './AdjustPicker.vue'
import DataProvenance from './DataProvenance.vue'
import type { MarketDataMetadata } from '../market-data-contract'
import StockHistoryMenu from './StockHistoryMenu.vue'
import { fetchBars, fetchRadarSnapshot, formatError } from '../api'
import { useAuth } from '../auth'
import { detectMarket, marketLabel } from '../market'
import { getLastStockCode, recordStockHistory } from '../stock-history'
import { useBacktestStore } from '../stores/backtest'
import type { StockHistoryItem } from '../stock-history'
import type { Category } from '../types'
import { useMarketPreferences } from '../market-preferences'
import { latestResearchRequest } from '../research-input'
import { sameReviewInput, snapshotForReview, type RadarReview } from '../radar-review'

const props = defineProps<{ review?: RadarReview | null }>()

const store = useBacktestStore()
const { adjustMode, adjustOptions } = useMarketPreferences()
const code = defineModel<string>('code', { default: getLastStockCode() })
const category = defineModel<Category>('category', { default: 'DAY' })
const startDate = defineModel<string>('startDate', { default: '2020-01-06' })
const endDate = defineModel<string>('endDate', {
  default: new Date().toISOString().slice(0, 10),
})

const error = ref('')
const loading = ref(false)
const metadata = ref<MarketDataMetadata | null>(null)
const requests = latestResearchRequest()
const {currentUser}=useAuth()
watch(()=>currentUser.value?.id,()=>{requests.invalidate();loading.value=false;metadata.value=null;error.value='';store.setOhlcv([], '', null, null)},{flush:'sync'})
watch([code, category, startDate, endDate, adjustMode, () => props.review], () => {
  requests.invalidate()
  if (loading.value) {
    loading.value = false
    error.value = '查询参数已改变，请重新加载行情'
    store.error = error.value
  }
}, { flush: 'sync' })
onBeforeUnmount(() => requests.invalidate())
const CATEGORIES: Category[] = ['DAY', 'WEEK', 'MONTH', 'MIN_5', 'MIN_15', 'MIN_30', 'MIN_60']
const CATEGORY_OPTIONS = CATEGORIES.map((value) => ({ value, label: value }))
const detectedMarket = computed(() => (code.value && /^\d{6}$/.test(code.value)
  ? marketLabel(detectMarket(code.value))
  : ''))

function selectHistory(item: StockHistoryItem) {
  code.value = item.code
  category.value = item.category
  if (item.startDate) startDate.value = item.startDate
  if (item.endDate) endDate.value = item.endDate
}

async function loadBars(manual = false): Promise<boolean> {
  if (!/^\d{6}$/.test(code.value)) {
    error.value = '股票代码必须是 6 位数字'
    store.error = error.value
    return false
  }
  if (!props.review?.evidence && startDate.value > endDate.value) {
    error.value = '开始日期不得晚于结束日期'
    store.error = error.value
    return false
  }

  loading.value = true
  store.clearResult()
  store.setOhlcv([], '', null, null)
  const ticket = requests.begin()
  const query = { code: code.value, market: detectMarket(code.value), category: category.value,
    startDate: startDate.value, endDate: endDate.value, adjust: adjustMode.value }
  const review = props.review
  const owner=currentUser.value?.id
  error.value = ''
  metadata.value = null
  try {
    const market = query.market
    if (review && !sameReviewInput(review, query.code, query.category, query.adjust)) throw Error('复核行情条件不一致，已停止')
    const frozen=review?.evidence?await queryAction(manual)(()=>fetchRadarSnapshot(review,owner??'',ticket.signal)):null
    if(!ticket.current())return false
    if(frozen)metadata.value=frozen.metadata
    let bars = frozen?.bars ?? await queryAction(manual)(() => fetchBars(
      market, query.code, query.category, query.startDate, query.endDate, query.adjust,
      (value) => { if (ticket.current()) metadata.value = value }, ticket.signal,
    ))
    if (!ticket.current()) return false
    if (review) {
      if (!sameReviewInput(review, query.code, query.category, query.adjust) || !metadata.value) throw Error('复核行情条件不一致，已停止')
      const snapshot = frozen ?? snapshotForReview({ bars, metadata: metadata.value }, review)
      bars = snapshot.bars
      metadata.value = snapshot.metadata
    }
    if (bars.length < 2) {
      error.value = `该日期范围内仅取到 ${bars.length} 根 K 线，不足以回测`
      store.error = error.value
      return false
    }
    const range = frozen?`${bars[0]!.datetime} ~ ${bars.at(-1)!.datetime} · 原扫描行情`:`${query.startDate} ~ ${query.endDate}`
    // Frozen inputs include their original warmup, not this form's default range.
    const loadedQuery = frozen ? { ...query, startDate: bars[0]!.datetime.slice(0,10), endDate: bars.at(-1)!.datetime.slice(0,10) } : query
    const adjustLabel = adjustOptions.find((item) => item.value === query.adjust)?.label ?? ''
    store.setOhlcv(bars, `${market}:${query.code} ${query.category} · ${adjustLabel} · ${range}`, metadata.value, loadedQuery, frozen?.radarSource??null)
    store.clearResult()
    recordStockHistory({
      code: query.code,
      category: query.category,
      startDate: loadedQuery.startDate,
      endDate: loadedQuery.endDate,
    })
    return true
  } catch (e) {
    if (!ticket.current()) return false
    metadata.value = null
    error.value = formatError(e)
    store.error = error.value
    return false
  } finally {
    if (ticket.current()) loading.value = false
  }
}

defineExpose({ loadBars, loading })
</script>

<template>
  <div class="symbol-picker">
    <div class="field code-field">
      <div class="code-label-row">
        <label>代码</label>
        <StockHistoryMenu @select="selectHistory" />
      </div>
      <input v-model="code" autocomplete="off" inputmode="numeric" maxlength="6" placeholder="6位代码（市场自动识别）" />
      <span v-if="detectedMarket" class="market-tag">{{ detectedMarket }}</span>
    </div>
    <div class="field">
      <label>周期</label>
      <MacSelect v-model="category" :options="CATEGORY_OPTIONS" aria-label="行情周期" />
    </div>
    <AdjustPicker />
    <p v-if="review?.evidence" class="frozen-range">原扫描复核使用保存的全部行情与预热区间，不按本页日期裁剪。</p>
    <div v-else class="row">
      <div class="field"><label>开始日期</label><input v-model="startDate" type="date" /></div>
      <div class="field"><label>结束日期</label><input v-model="endDate" type="date" /></div>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="store.barsSource" class="ok">已加载：{{ store.barsSource }}（{{ store.ohlcv.length }} 根）</p>
    <DataProvenance v-if="store.barsMetadata && !loading" :metadata="store.barsMetadata" :count="store.ohlcv.length" />
  </div>
</template>

<style scoped>
.frozen-range{font-size:11px;line-height:1.8;color:var(--text-muted);margin:8px 0}
.code-field{position:relative}.code-label-row{display:flex;min-height:23px;align-items:flex-start;justify-content:space-between;gap:8px}.code-field input{padding-right:70px}.market-tag{position:absolute;right:8px;bottom:8px;padding:1px 6px;color:var(--text-dim);background:var(--bg-elevated);border:1px solid var(--border);border-radius:3px;font-size:11px}.err{margin-top:8px;color:var(--up);font-size:12px}.ok{margin-top:8px;color:var(--down);font-size:12px}
</style>
