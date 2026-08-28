<script setup lang="ts">
import { computed, ref } from 'vue'

import MacSelect from './MacSelect.vue'
import AdjustPicker from './AdjustPicker.vue'
import StockHistoryMenu from './StockHistoryMenu.vue'
import { fetchBars, formatError } from '../api'
import { detectMarket, marketLabel } from '../market'
import { recordStockHistory } from '../stock-history'
import { useBacktestStore } from '../stores/backtest'
import type { StockHistoryItem } from '../stock-history'
import type { Category } from '../types'
import { useMarketPreferences } from '../market-preferences'

const store = useBacktestStore()
const { adjustMode, adjustOptions } = useMarketPreferences()
const code = defineModel<string>('code', { default: '000001' })
const category = defineModel<Category>('category', { default: 'DAY' })
const startDate = defineModel<string>('startDate', { default: '2020-01-06' })
const endDate = defineModel<string>('endDate', {
  default: new Date().toISOString().slice(0, 10),
})

const error = ref('')
const loading = ref(false)
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

async function loadBars(): Promise<boolean> {
  if (!/^\d{6}$/.test(code.value)) {
    error.value = '股票代码必须是 6 位数字'
    store.error = error.value
    return false
  }
  if (startDate.value >= endDate.value) {
    error.value = '开始日期必须早于结束日期'
    store.error = error.value
    return false
  }

  loading.value = true
  error.value = ''
  try {
    const market = detectMarket(code.value)
    const bars = await fetchBars(
      market, code.value, category.value, startDate.value, endDate.value, adjustMode.value,
    )
    if (bars.length < 2) {
      error.value = `该日期范围内仅取到 ${bars.length} 根 K 线，不足以回测`
      store.error = error.value
      return false
    }
    const range = `${startDate.value} ~ ${endDate.value}`
    const adjustLabel = adjustOptions.find((item) => item.value === adjustMode.value)?.label ?? ''
    store.setOhlcv(bars, `${market}:${code.value} ${category.value} · ${adjustLabel} · ${range}`)
    store.clearResult()
    recordStockHistory({
      code: code.value,
      category: category.value,
      startDate: startDate.value,
      endDate: endDate.value,
    })
    return true
  } catch (e) {
    error.value = formatError(e)
    store.error = error.value
    return false
  } finally {
    loading.value = false
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
    <div class="row">
      <div class="field"><label>开始日期</label><input v-model="startDate" type="date" /></div>
      <div class="field"><label>结束日期</label><input v-model="endDate" type="date" /></div>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="store.barsSource" class="ok">已加载：{{ store.barsSource }}（{{ store.ohlcv.length }} 根）</p>
  </div>
</template>

<style scoped>
.code-field{position:relative}.code-label-row{display:flex;min-height:23px;align-items:flex-start;justify-content:space-between;gap:8px}.code-field input{padding-right:70px}.market-tag{position:absolute;right:8px;bottom:8px;padding:1px 6px;color:var(--text-dim);background:var(--bg-elevated);border:1px solid var(--border);border-radius:3px;font-size:11px}.err{margin-top:8px;color:var(--up);font-size:12px}.ok{margin-top:8px;color:var(--down);font-size:12px}
</style>
