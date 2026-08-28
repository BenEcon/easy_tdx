<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DataGrid from '../components/DataGrid.vue'
import MacSelect from '../components/MacSelect.vue'
import StockQueryField from '../components/StockQueryField.vue'
import {
  fetchBlockInfo, fetchBoardBelong, fetchBoardChangeRanking, fetchBoardList,
  fetchBoardMembers, fetchBoardRanking, fetchBoardSummary, formatError,
} from '../api'
import { detectMarket } from '../market'
import { getLastStockCode, recordStockHistory } from '../stock-history'

type Row = Record<string, unknown>
type Mode = 'live' | 'ranking' | 'change' | 'classic'
const mode = ref<Mode>('live')
const boardType = ref('HY')
const sortColumn = ref('CHANGE_PCT')
const changeDays = ref('20')
const blockFile = ref('block_gn.dat')
const boards = ref<Row[]>([])
const members = ref<Row[]>([])
const belongs = ref<Row[]>([])
const summary = ref<Record<string, unknown>>({})
const selectedBoard = ref<Row | null>(null)
const stockCode = ref(getLastStockCode())
const loadingBoards = ref(false)
const loadingMembers = ref(false)
const loadingBelong = ref(false)
const error = ref('')

const boardTypes = [
  { value: 'HY', label: '通达信行业' }, { value: 'HY2', label: '二级行业' },
  { value: 'GN', label: '概念板块' }, { value: 'FG', label: '风格板块' },
  { value: 'DQ', label: '地区板块' }, { value: 'ALL', label: '全部板块' },
]
const sortOptions = [
  { value: 'CHANGE_PCT', label: '当日涨跌幅' }, { value: 'SPEED', label: '实时涨速' },
  { value: 'CHANGE_5D', label: '5 日涨幅' }, { value: 'CHANGE_20D', label: '20 日涨幅' },
  { value: 'CHANGE_60D', label: '60 日涨幅' }, { value: 'YTD', label: '年初至今' },
]
const dayOptions = [
  { value: '5', label: '5 日' }, { value: '10', label: '10 日' },
  { value: '20', label: '20 日' }, { value: '60', label: '60 日' },
]
const blockOptions = [
  { value: 'block_zs.dat', label: '行业指数' },
  { value: 'block_gn.dat', label: '概念板块' },
  { value: 'block_fg.dat', label: '风格板块' },
]
const selectedName = computed(() => String(selectedBoard.value?.name ?? selectedBoard.value?.board_name ?? '选择左侧板块'))
const summaryEntries = computed(() => Object.entries(summary.value)
  .filter(([, value]) => ['string', 'number'].includes(typeof value))
  .slice(0, 6))
const boardColumns = [
  { key: 'code', label: '板块代码' }, { key: 'name', label: '板块名称' },
  { key: 'price', label: '最新点位' }, { key: 'change_pct', label: '涨跌幅' },
  { key: 'symbol_name', label: '领涨股' }, { key: 'symbol_change_pct', label: '领涨幅' },
]
const memberColumns = [
  { key: 'code', label: '代码' }, { key: 'name', label: '名称' },
  { key: 'close', label: '最新价' }, { key: 'change_pct', label: '涨跌幅' },
  { key: 'vol', label: '成交量' }, { key: 'amount', label: '成交额' },
  { key: 'turnover_rate', label: '换手率' },
]
const summaryLabels: Record<string, string> = {
  member_count: '成分数量', amount: '成交额', vol: '成交量',
  main_net_amount: '主力净额', main_net_3d: '3 日主力净额', main_net_5d: '5 日主力净额',
  change_pct: '板块涨跌幅', up_count: '上涨家数', down_count: '下跌家数',
}

function summaryLabel(key: string): string {
  return summaryLabels[key] ?? key.replaceAll('_', ' ')
}

function summaryValue(key: string, input: unknown): string {
  if (typeof input !== 'number') return String(input)
  const value = /change_pct|rate/.test(key) ? `${input.toFixed(2)}%` : input.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return value
}

function percentage(priceValue: unknown, preCloseValue: unknown): number | undefined {
  const price = Number(priceValue)
  const preClose = Number(preCloseValue)
  return Number.isFinite(price) && Number.isFinite(preClose) && preClose !== 0
    ? ((price / preClose) - 1) * 100
    : undefined
}

const displayBoards = computed(() => boards.value.map((row) => ({
  ...row,
  change_pct: percentage(row.price, row.pre_close),
  symbol_change_pct: percentage(row.symbol_price, row.symbol_pre_close),
})))
const displayMembers = computed(() => members.value.map((row) => ({
  ...row,
  change_pct: percentage(row.close ?? row.price, row.last_close ?? row.pre_close),
})))

async function loadBoards() {
  loadingBoards.value = true
  error.value = ''
  try {
    const response = mode.value === 'live'
      ? await fetchBoardList({ boardType: boardType.value, sortColumn: sortColumn.value })
      : mode.value === 'ranking'
        ? await fetchBoardRanking({ boardType: boardType.value, topN: 100 })
        : mode.value === 'change'
          ? await fetchBoardChangeRanking({ boardType: boardType.value, days: Number(changeDays.value), topN: 100 })
          : await fetchBlockInfo(blockFile.value)
    boards.value = response.data
    if (boards.value.length && mode.value !== 'classic') await selectBoard(boards.value[0])
    else { selectedBoard.value = null; members.value = []; summary.value = {} }
  } catch (e) {
    error.value = formatError(e)
    boards.value = []
  } finally {
    loadingBoards.value = false
  }
}

async function selectBoard(row: Row) {
  const symbol = String(row.code ?? row.board_code ?? row.board_symbol ?? '')
  if (!symbol) return
  selectedBoard.value = row
  loadingMembers.value = true
  try {
    const [memberResult, summaryResult] = await Promise.allSettled([
      fetchBoardMembers(symbol), fetchBoardSummary(symbol),
    ])
    members.value = memberResult.status === 'fulfilled' ? memberResult.value.data : []
    summary.value = summaryResult.status === 'fulfilled' ? summaryResult.value.data : {}
    if (!members.value.length && memberResult.status === 'rejected') throw memberResult.reason
  } catch (e) {
    error.value = formatError(e)
    members.value = []
  } finally {
    loadingMembers.value = false
  }
}

function switchMode(next: Mode) {
  mode.value = next
  void loadBoards()
}

async function queryBelong() {
  if (!/^\d{6}$/.test(stockCode.value)) {
    error.value = '股票代码必须是 6 位数字'
    return
  }
  loadingBelong.value = true
  error.value = ''
  try {
    const market = detectMarket(stockCode.value)
    belongs.value = (await fetchBoardBelong(market, stockCode.value)).data
    recordStockHistory({ code: stockCode.value, category: 'DAY' })
  } catch (e) {
    error.value = formatError(e)
    belongs.value = []
  } finally {
    loadingBelong.value = false
  }
}

onMounted(loadBoards)
</script>

<template>
  <div class="board-page">
    <nav class="mode-tabs">
      <button :class="{ active: mode === 'live' }" @click="switchMode('live')">实时板块</button>
      <button :class="{ active: mode === 'ranking' }" @click="switchMode('ranking')">聚合排行</button>
      <button :class="{ active: mode === 'change' }" @click="switchMode('change')">区间涨幅</button>
      <button :class="{ active: mode === 'classic' }" @click="switchMode('classic')">传统板块库</button>
    </nav>
    <section class="control-card">
      <div class="control-intro"><span>SECTOR LENS</span><h2>板块研究</h2><p>从板块强弱快速下钻到成分股，也可反查个股所属主题。</p></div>
      <div v-if="mode !== 'classic'" class="select-control"><label>板块类型</label><MacSelect v-model="boardType" :options="boardTypes" /></div>
      <div v-if="mode === 'live'" class="select-control"><label>排序周期</label><MacSelect v-model="sortColumn" :options="sortOptions" /></div>
      <div v-else-if="mode === 'change'" class="select-control"><label>统计区间</label><MacSelect v-model="changeDays" :options="dayOptions" /></div>
      <div v-else-if="mode === 'classic'" class="select-control"><label>板块文件</label><MacSelect v-model="blockFile" :options="blockOptions" /></div>
      <button class="primary refresh-btn action-button" :disabled="loadingBoards" @click="loadBoards">{{ loadingBoards ? '更新中' : '更新板块' }}</button>
    </section>
    <p v-if="error" class="error-banner status-banner">{{ error }}</p>

    <section class="split-workspace">
      <div class="pane board-pane">
        <header><div><h3>板块排行</h3><p>{{ boards.length }} 个板块 · 点击查看成分</p></div><span class="pane-badge">RANK</span></header>
        <DataGrid :rows="displayBoards" :columns="mode === 'live' ? boardColumns : []" :selectable="mode !== 'classic'" :empty-text="loadingBoards ? '正在获取板块…' : '暂无板块数据'" @select="selectBoard" />
      </div>
      <div class="pane member-pane">
        <header><div><h3>{{ selectedName }}</h3><p>{{ members.length }} 只成分股</p></div><span v-if="loadingMembers" class="loading-label">载入中</span></header>
        <div v-if="summaryEntries.length" class="summary-strip">
          <div v-for="([key, value]) in summaryEntries" :key="key"><small>{{ summaryLabel(key) }}</small><strong>{{ summaryValue(key, value) }}</strong></div>
        </div>
        <DataGrid :rows="displayMembers" :columns="memberColumns" :empty-text="loadingMembers ? '正在加载成分股…' : '请选择板块'" />
      </div>
    </section>

    <section class="belong-card">
      <div class="belong-query">
        <StockQueryField v-model="stockCode" label="个股板块归属" />
        <button class="primary action-button belong-action" :disabled="loadingBelong" @click="queryBelong">
          <svg v-if="!loadingBelong" class="button-icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.5" cy="8.5" r="4.5"/><path d="m12 12 4 4" /></svg>
          <svg v-else class="button-icon spinning" viewBox="0 0 20 20" aria-hidden="true"><path d="M16 6.5V3l-2 2a6.5 6.5 0 1 0 1.5 8" /></svg>
          <span>{{ loadingBelong ? '查询中' : '查询归属' }}</span>
        </button>
      </div>
      <div class="belong-result">
        <DataGrid :rows="belongs" :columns="[
          { key: 'board_code', label: '板块代码' }, { key: 'board_name', label: '板块名称' },
          { key: 'close', label: '现价' }, { key: 'pre_close', label: '昨收' },
        ]" empty-text="输入股票代码，查看它所属的行业、概念与风格板块" />
      </div>
    </section>
  </div>
</template>

<style scoped>
.board-page{display:flex;height:100%;min-height:0;flex-direction:column;gap:11px}.mode-tabs{display:flex;padding:3px;background:rgba(0,0,0,.18);border:1px solid var(--border);border-radius:10px}.mode-tabs button{min-height:29px;color:var(--text-dim);background:transparent;border-color:transparent;box-shadow:none}.mode-tabs button.active{color:var(--text);background:rgba(255,255,255,.08);border-color:var(--border)}.control-card{display:flex;align-items:flex-end;gap:10px;padding:12px 16px;background:linear-gradient(115deg,rgba(94,92,230,.08),rgba(255,255,255,.018));border:1px solid var(--border);border-radius:14px}.control-intro{min-width:290px;margin-right:auto}.control-intro span{color:#8f8cff;font-size:9px;font-weight:750;letter-spacing:.16em}.control-intro h2{margin-top:2px;font-size:18px}.control-intro p{color:var(--text-dim);font-size:10px}.select-control{width:145px}.refresh-btn{min-height:34px}.status-banner{padding:8px 11px;border-radius:8px;font-size:11px}.split-workspace{display:grid;min-height:300px;flex:1;grid-template-columns:minmax(350px,.85fr) minmax(440px,1.15fr);gap:12px}.pane,.belong-card{display:flex;min-height:0;flex-direction:column;padding:12px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px}.pane header{display:flex;align-items:center;justify-content:space-between;padding:0 3px 9px}.pane h3{font-size:13px}.pane p{color:var(--text-dim);font-size:10px}.pane-badge{padding:2px 6px;color:#8f8cff;background:rgba(94,92,230,.09);border:1px solid rgba(94,92,230,.18);border-radius:5px;font-size:8px;font-weight:750}.loading-label{color:var(--accent);font-size:10px}.summary-strip{display:flex;gap:6px;margin-bottom:8px;overflow-x:auto}.summary-strip>div{min-width:88px;padding:6px 8px;background:rgba(0,0,0,.17);border:1px solid var(--border);border-radius:7px}.summary-strip small{display:block;overflow:hidden;color:var(--text-dim);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.summary-strip strong{display:block;overflow:hidden;color:var(--text-muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.belong-card{display:grid;height:160px;min-height:160px;grid-template-columns:225px 1fr;gap:12px}.belong-query{display:flex;flex-direction:column;justify-content:center;padding:4px}.belong-query button{min-height:35px;margin-top:9px}.belong-result{min-width:0;min-height:0}.belong-result :deep(.data-grid-wrap){min-height:130px}.belong-result :deep(.empty-state){min-height:130px}@media(max-width:1050px){.control-intro p{display:none}.control-intro{min-width:190px}.split-workspace{grid-template-columns:1fr}.board-page{overflow:auto}.pane{min-height:320px}}
.belong-query .belong-action{width:100%;min-height:34px}
</style>
