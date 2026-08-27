<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import ChartFrame from '../components/ChartFrame.vue'
import DataGrid from '../components/DataGrid.vue'
import KlineChart from '../components/KlineChart.vue'
import MacSelect from '../components/MacSelect.vue'
import { fetchExtendedInstruments, fetchExtendedMarket, fetchExtendedMarkets, formatError } from '../api'
import type { Bar } from '../types'

type Row = Record<string, unknown>
type Tab = 'bars' | 'quote' | 'minute' | 'transaction' | 'instruments'

const tab = ref<Tab>('bars')
const market = ref('31')
const code = ref('00700')
const category = ref('DAY')
const rows = ref<Row[]>([])
const markets = ref<Row[]>([])
const query = ref('')
const loading = ref(false)
const error = ref('')

const tabs: Array<{ value: Tab; label: string }> = [
  { value: 'bars', label: 'K线' }, { value: 'quote', label: '实时报价' },
  { value: 'minute', label: '分时' }, { value: 'transaction', label: '逐笔' },
  { value: 'instruments', label: '合约目录' },
]
const fallbackMarkets = [
  { value: '31', label: '香港主板' }, { value: '48', label: '香港创业板' },
  { value: '74', label: '外盘/美股' }, { value: '47', label: '中金所期货' },
  { value: '30', label: '上海期货' }, { value: '29', label: '大连商品' },
  { value: '28', label: '郑州商品' }, { value: '16', label: 'COMEX' },
]
const marketOptions = computed(() => markets.value.length
  ? markets.value.map((row) => ({ value: String(row.market), label: String(row.name ?? row.short_name ?? row.market) }))
  : fallbackMarkets)
const categoryOptions = [
  { value: 'DAY', label: '日线' }, { value: 'WEEK', label: '周线' },
  { value: 'MONTH', label: '月线' }, { value: 'MIN_5', label: '5分钟' },
  { value: 'MIN_30', label: '30分钟' }, { value: 'MIN_60', label: '60分钟' },
]
const selectedMarketName = computed(() => marketOptions.value.find((item) => item.value === market.value)?.label ?? market.value)
const displayRows = computed(() => {
  if (tab.value !== 'instruments' || !query.value.trim()) return rows.value
  const keyword = query.value.trim().toLowerCase()
  return rows.value.filter((row) => String(row.code ?? '').toLowerCase().includes(keyword) || String(row.name ?? row.desc ?? '').toLowerCase().includes(keyword))
})
const bars = computed<Bar[]>(() => rows.value.map((row) => ({
  datetime: String(row.datetime ?? ''), open: Number(row.open), high: Number(row.high),
  low: Number(row.low), close: Number(row.close), vol: Number(row.vol ?? row.trade ?? 0),
  amount: Number(row.amount ?? 0),
})).filter((bar) => bar.datetime && Number.isFinite(bar.close)).sort((a, b) => a.datetime.localeCompare(b.datetime)))
const quote = computed(() => rows.value[0] ?? {})
const changePct = computed(() => {
  const price = Number(quote.value.price ?? quote.value.close)
  const preClose = Number(quote.value.pre_close)
  return Number.isFinite(price) && Number.isFinite(preClose) && preClose ? ((price / preClose) - 1) * 100 : null
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = tab.value === 'instruments'
      ? (await fetchExtendedInstruments(market.value, 0, 1000)).data
      : (await fetchExtendedMarket(tab.value, market.value, code.value.trim(), category.value)).data
  } catch (e) {
    rows.value = []
    error.value = `${formatError(e)}。如提示“扩展市场客户端未启用”，请在服务器启用扩展行情连接。`
  } finally {
    loading.value = false
  }
}

function switchTab(next: Tab) { tab.value = next; rows.value = []; void load() }

async function initialize() {
  try { markets.value = (await fetchExtendedMarkets()).data } catch { markets.value = [] }
  await load()
}
onMounted(initialize)
</script>

<template>
  <div class="extended-page">
    <section class="extended-header">
      <div class="intro"><span>GLOBAL TAPE</span><h2>扩展市场</h2><p>港股、期货与外盘行情使用独立扩展数据连接。</p></div>
      <div class="field market-field"><label>市场</label><MacSelect v-model="market" :options="marketOptions" /></div>
      <label v-if="tab !== 'instruments'" class="field code-field"><span>证券 / 合约代码</span><input v-model="code" autocomplete="off" placeholder="00700 / AAPL / IFL0" @keyup.enter="load" /></label>
      <div v-if="tab === 'bars'" class="field period-field"><label>周期</label><MacSelect v-model="category" :options="categoryOptions" /></div>
      <label v-if="tab === 'instruments'" class="field search-field"><span>筛选合约</span><input v-model="query" type="search" placeholder="输入代码或名称" /></label>
      <button class="primary load-button" :disabled="loading" @click="load">{{ loading ? '读取中' : '查询行情' }}</button>
    </section>
    <nav class="tab-bar"><button v-for="item in tabs" :key="item.value" :class="{ active: tab === item.value }" @click="switchTab(item.value)">{{ item.label }}</button><span class="connection-mark"><i></i>EX 7727</span></nav>
    <p v-if="error" class="error-banner status-banner">{{ error }}</p>

    <section v-if="tab === 'quote' && rows.length" class="quote-strip">
      <div><small>标的</small><strong>{{ code }} · {{ selectedMarketName }}</strong></div>
      <div><small>最新价</small><strong>{{ Number(quote.price ?? 0).toFixed(2) }}</strong></div>
      <div><small>涨跌幅</small><strong :class="changePct !== null && changePct >= 0 ? 'up' : 'down'">{{ changePct === null ? '—' : `${changePct.toFixed(2)}%` }}</strong></div>
      <div><small>今开 / 最高 / 最低</small><strong>{{ Number(quote.open ?? 0).toFixed(2) }} / {{ Number(quote.high ?? 0).toFixed(2) }} / {{ Number(quote.low ?? 0).toFixed(2) }}</strong></div>
    </section>

    <section v-if="tab === 'bars'" class="chart-panel">
      <ChartFrame :title="`${selectedMarketName} · ${code}`" :description="`${category} · ${bars.length} 根 K 线 · 支持全屏与技术指标`"><KlineChart :bars="bars" :trades="[]" /></ChartFrame>
    </section>
    <section v-else class="data-panel">
      <header><div><h3>{{ tabs.find(item => item.value === tab)?.label }}</h3><p>{{ displayRows.length }} 条记录 · 数据来自扩展行情服务器</p></div><span>EX</span></header>
      <DataGrid :rows="displayRows" :empty-text="loading ? '正在获取扩展行情…' : '暂无数据'" />
    </section>
  </div>
</template>

<style scoped>
.extended-page{display:flex;height:100%;min-height:0;flex-direction:column;gap:12px}.extended-header{display:flex;align-items:flex-end;gap:10px;padding:14px 16px;background:linear-gradient(120deg,rgba(255,159,10,.085),rgba(94,92,230,.035));border:1px solid var(--border);border-radius:14px}.intro{min-width:270px;margin-right:auto}.intro span{color:#ffb340;font-size:9px;font-weight:750;letter-spacing:.16em}.intro h2{margin-top:2px;font-size:18px}.intro p{color:var(--text-dim);font-size:10px}.field{display:block;margin:0}.field>span,.field>label{display:block;margin-bottom:5px;color:var(--text-muted);font-size:11px}.market-field{width:155px}.code-field{width:180px}.period-field{width:120px}.search-field{width:240px}.load-button{min-height:36px}.tab-bar{display:flex;align-items:center;padding:3px;background:rgba(0,0,0,.18);border:1px solid var(--border);border-radius:10px}.tab-bar button{min-height:30px;color:var(--text-dim);background:transparent;border-color:transparent;box-shadow:none}.tab-bar button.active{color:var(--text);background:rgba(255,255,255,.08);border-color:var(--border)}.connection-mark{display:flex;align-items:center;gap:6px;margin-left:auto;padding:0 8px;color:var(--text-dim);font-size:8px;font-weight:700;letter-spacing:.08em}.connection-mark i{width:6px;height:6px;background:#ff9f0a;border-radius:50%}.status-banner{padding:8px 11px;border-radius:8px;font-size:11px}.quote-strip{display:grid;grid-template-columns:1.2fr .7fr .7fr 1.2fr;gap:1px;overflow:hidden;background:var(--border);border:1px solid var(--border);border-radius:11px}.quote-strip>div{padding:10px 12px;background:#17181d}.quote-strip small{display:block;color:var(--text-dim);font-size:9px}.quote-strip strong{font-size:12px}.up{color:var(--up)}.down{color:var(--down)}.chart-panel,.data-panel{min-height:0;flex:1;padding:12px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px}.chart-panel :deep(.kline-chart){height:calc(100% - 2px);min-height:390px}.chart-panel :deep(.chart-frame){height:100%}.chart-panel :deep(.chart-frame-content){height:calc(100% - 48px)}.data-panel{display:flex;flex-direction:column}.data-panel>header{display:flex;align-items:center;justify-content:space-between;padding:0 3px 9px}.data-panel h3{font-size:13px}.data-panel p{color:var(--text-dim);font-size:10px}.data-panel header>span{padding:2px 6px;color:#ffb340;background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.18);border-radius:5px;font-size:8px;font-weight:750}@media(max-width:1050px){.intro{min-width:175px}.intro p{display:none}.extended-header{flex-wrap:wrap}.extended-page{overflow:auto}.chart-panel,.data-panel{min-height:500px}}
</style>
