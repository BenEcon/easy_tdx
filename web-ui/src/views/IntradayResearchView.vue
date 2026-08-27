<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ChartFrame from '../components/ChartFrame.vue'
import DataGrid from '../components/DataGrid.vue'
import IntradayChart from '../components/IntradayChart.vue'
import MacSelect from '../components/MacSelect.vue'
import StockQueryField from '../components/StockQueryField.vue'
import { fetchIndexBars, fetchMinuteData, fetchServerSession, fetchTransactionData, formatError } from '../api'
import { detectMarket } from '../market'
import { recordStockHistory, stockDisplayName } from '../stock-history'

type Row = Record<string, unknown>
type Tab = 'minute' | 'transactions' | 'index' | 'session'

const code = ref('000001')
const date = ref('')
const tab = ref<Tab>('minute')
const indexSymbol = ref('SH:000001')
const category = ref('DAY')
const rows = ref<Row[]>([])
const loading = ref(false)
const error = ref('')
const live = ref(false)
const liveState = ref<'idle' | 'connecting' | 'connected' | 'error'>('idle')
const liveTick = ref<Row | null>(null)
let socket: WebSocket | null = null

const tabs: Array<{ value: Tab; label: string }> = [
  { value: 'minute', label: '分时走势' },
  { value: 'transactions', label: '逐笔成交' },
  { value: 'index', label: '指数行情' },
  { value: 'session', label: '交易时段' },
]
const indexOptions = [
  { value: 'SH:000001', label: '000001-上证指数' },
  { value: 'SZ:399001', label: '399001-深证成指' },
  { value: 'SZ:399006', label: '399006-创业板指' },
  { value: 'SH:000300', label: '000300-沪深300' },
]
const categoryOptions = [
  { value: 'DAY', label: '日线' }, { value: 'WEEK', label: '周线' },
  { value: 'MONTH', label: '月线' }, { value: 'MIN_5', label: '5分钟' },
  { value: 'MIN_30', label: '30分钟' }, { value: 'MIN_60', label: '60分钟' },
]
const displayRows = computed(() => rows.value.map((row, index) => {
  if (tab.value === 'minute') return { time: minuteLabel(index), ...row }
  if (tab.value === 'transactions') {
    const direction = Number(row.buyorsell)
    return {
      ...row,
      time: `${String(row.hour ?? '').padStart(2, '0')}:${String(row.minute ?? '').padStart(2, '0')}`,
      direction: direction === 0 ? '主动买入' : direction === 1 ? '主动卖出' : direction === 8 ? '集合竞价' : '中性成交',
    }
  }
  return row
}))
const stockName = computed(() => stockDisplayName(code.value))
const liveLabel = computed(() => ({
  idle: '开启实时', connecting: '连接中', connected: '实时已连接', error: '重新连接',
}[liveState.value]))

function minuteLabel(index: number): string {
  const minutes = index < 120 ? 570 + index : 780 + index - 120
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
}

function disconnectLive() {
  socket?.close()
  socket = null
  live.value = false
  liveState.value = 'idle'
}

function toggleLive() {
  if (socket) {
    disconnectLive()
    return
  }
  const market = detectMarket(code.value)
  live.value = true
  liveState.value = 'connecting'
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  socket = new WebSocket(`${protocol}//${location.host}/api/v1/ws/realtime/${market}${code.value}`)
  socket.onopen = () => { liveState.value = 'connected' }
  socket.onmessage = (event) => {
    const payload = JSON.parse(String(event.data)) as Row
    if (payload.type !== 'ping' && payload.type !== 'status') liveTick.value = payload
  }
  socket.onerror = () => { liveState.value = 'error' }
  socket.onclose = () => {
    socket = null
    live.value = false
    if (liveState.value !== 'error') liveState.value = 'idle'
  }
}

async function load() {
  if (tab.value !== 'session' && tab.value !== 'index' && !/^\d{6}$/.test(code.value)) {
    error.value = '股票代码必须是 6 位数字'
    return
  }
  loading.value = true
  error.value = ''
  try {
    if (tab.value === 'minute') rows.value = (await fetchMinuteData(detectMarket(code.value), code.value, date.value || undefined)).data
    else if (tab.value === 'transactions') rows.value = (await fetchTransactionData(detectMarket(code.value), code.value, date.value || undefined)).data
    else if (tab.value === 'index') {
      const [market, indexCode] = indexSymbol.value.split(':')
      rows.value = (await fetchIndexBars(market, indexCode, category.value)).data
    } else rows.value = (await fetchServerSession()).data
    if (tab.value === 'minute' || tab.value === 'transactions') recordStockHistory({ code: code.value, category: 'DAY' })
  } catch (e) {
    rows.value = []
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

function switchTab(next: Tab) {
  tab.value = next
  rows.value = []
  void load()
}

onMounted(load)
onBeforeUnmount(disconnectLive)
</script>

<template>
  <div class="intraday-page">
    <section class="query-strip">
      <div class="intro"><span>INTRADAY LAB</span><h2>盘中研究</h2><p>分时、逐笔、指数与实时快照集中观察。</p></div>
      <template v-if="tab === 'minute' || tab === 'transactions'">
        <StockQueryField v-model="code" />
        <label class="date-field"><span>交易日期</span><input v-model="date" type="date" /></label>
      </template>
      <template v-else-if="tab === 'index'">
        <div class="select-field"><label>指数</label><MacSelect v-model="indexSymbol" :options="indexOptions" /></div>
        <div class="select-field period"><label>周期</label><MacSelect v-model="category" :options="categoryOptions" /></div>
      </template>
      <button class="primary query-button" :disabled="loading" @click="load">
        <svg class="button-icon" :class="{ spinning: loading }" viewBox="0 0 20 20"><path d="M10 3a7 7 0 1 1-5.2 2.3M3 3v4h4" /></svg>
        {{ loading ? '读取中' : '更新数据' }}
      </button>
    </section>

    <nav class="tab-bar">
      <button v-for="item in tabs" :key="item.value" :class="{ active: tab === item.value }" @click="switchTab(item.value)">{{ item.label }}</button>
      <button v-if="tab === 'minute'" class="live-toggle" :class="{ connected: liveState === 'connected' }" @click="toggleLive">
        <span class="status-dot"></span>{{ liveLabel }}
      </button>
    </nav>

    <p v-if="error" class="error-banner status-banner">{{ error }}</p>
    <section v-if="liveTick" class="live-strip">
      <span>实时快照</span><strong>{{ stockName }}</strong>
      <b>{{ Number(liveTick.price ?? 0).toFixed(2) }}</b>
      <small>成交量 {{ Number(liveTick.volume ?? 0).toLocaleString('zh-CN') }}</small>
    </section>

    <section v-if="tab === 'minute'" class="minute-workspace">
      <div class="chart-panel">
        <ChartFrame :title="`${stockName} 分时走势`" :description="date ? `${date} 历史分时` : '当日 240 分钟走势 · 支持全屏研究'">
          <IntradayChart :rows="rows" />
        </ChartFrame>
      </div>
      <div class="table-panel compact"><header><div><h3>分钟明细</h3><p>{{ rows.length }} 个时间点</p></div></header><DataGrid :rows="displayRows" :columns="[{ key: 'time', label: '时间' }, { key: 'price', label: '价格' }, { key: 'vol', label: '成交量' }]" :empty-text="loading ? '正在读取分时数据…' : '暂无分时数据'" /></div>
    </section>
    <section v-else class="table-panel">
      <header><div><h3>{{ tabs.find(item => item.value === tab)?.label }}</h3><p>{{ rows.length }} 条记录 · 数值保留 2 位小数</p></div><span class="source-badge">TDX</span></header>
      <DataGrid :rows="displayRows" :empty-text="loading ? '正在获取数据…' : '暂无数据'" />
    </section>
  </div>
</template>

<style scoped>
.intraday-page{display:flex;height:100%;min-height:0;flex-direction:column;gap:12px}.query-strip{display:flex;align-items:flex-end;gap:10px;padding:14px 16px;background:linear-gradient(120deg,rgba(10,132,255,.1),rgba(255,255,255,.018));border:1px solid var(--border);border-radius:14px}.intro{min-width:270px;margin-right:auto}.intro span{color:#5cacff;font-size:9px;font-weight:750;letter-spacing:.16em}.intro h2{margin-top:2px;font-size:18px}.intro p{color:var(--text-dim);font-size:10px}.date-field,.select-field{width:160px;margin:0}.date-field span,.select-field label{display:block;margin-bottom:5px;color:var(--text-muted);font-size:11px}.select-field.period{width:118px}.query-button{min-height:36px}.tab-bar{display:flex;align-items:center;padding:3px;background:rgba(0,0,0,.18);border:1px solid var(--border);border-radius:10px}.tab-bar>button{min-height:30px;color:var(--text-dim);background:transparent;border-color:transparent;box-shadow:none}.tab-bar>button.active{color:var(--text);background:rgba(255,255,255,.08);border-color:var(--border)}.tab-bar .live-toggle{margin-left:auto;color:var(--text-muted)}.live-toggle.connected{color:#6ce29c}.status-dot{width:6px;height:6px;background:currentColor;border-radius:50%;box-shadow:0 0 0 3px color-mix(in srgb,currentColor 14%,transparent)}.live-toggle.connected .status-dot{animation:live-pulse 1.8s ease-in-out infinite}.status-banner{padding:8px 11px;border-radius:8px;font-size:11px}.live-strip{display:flex;align-items:center;gap:12px;padding:8px 12px;color:var(--text-muted);background:rgba(48,209,88,.06);border:1px solid rgba(48,209,88,.16);border-radius:9px;font-size:10px}.live-strip span{color:#6ce29c;font-weight:700;letter-spacing:.06em}.live-strip strong{color:var(--text)}.live-strip b{margin-left:auto;color:var(--text);font-size:15px}.minute-workspace{display:grid;min-height:0;flex:1;grid-template-columns:minmax(560px,1.45fr) minmax(290px,.55fr);gap:12px}.chart-panel,.table-panel{min-height:0;padding:12px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px}.table-panel{display:flex;flex:1;flex-direction:column}.table-panel>header{display:flex;align-items:center;justify-content:space-between;padding:0 3px 9px}.table-panel h3{font-size:13px}.table-panel p{color:var(--text-dim);font-size:10px}.source-badge{padding:2px 6px;color:#5cacff;background:rgba(10,132,255,.09);border:1px solid rgba(10,132,255,.18);border-radius:5px;font-size:8px;font-weight:750}.compact{flex:auto}.compact :deep(.data-grid){min-width:260px}@keyframes live-pulse{50%{opacity:.45;box-shadow:0 0 0 6px rgba(48,209,88,0)}}@media(max-width:1050px){.intro{min-width:180px}.intro p{display:none}.minute-workspace{grid-template-columns:1fr}.intraday-page{overflow:auto}.chart-panel,.table-panel{min-height:360px}}
</style>
