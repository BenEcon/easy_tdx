<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DataGrid from '../components/DataGrid.vue'
import MacSelect from '../components/MacSelect.vue'
import {
  fetchMarketRanking, fetchMarketStat, fetchMarketStrength, fetchMarketUnusual,
  fetchSecurityCount, fetchSecurityDirectory, formatError,
} from '../api'

type Row = Record<string, unknown>
type Tab = 'ranking' | 'stat' | 'unusual' | 'directory' | 'strength'

const tab = ref<Tab>('ranking')
const category = ref('A')
const sortType = ref('CHANGE_PCT')
const market = ref('SH')
const directoryMarket = ref('SH')
const directoryQuery = ref('')
const securityTotal = ref(0)
const strengthPreset = ref<'steady' | 'breakout' | 'balanced'>('steady')
const strengthUniverse = ref<'all' | 'sh' | 'sz'>('all')
const rows = ref<Row[]>([])
const loading = ref(false)
const error = ref('')

function withChangePct(row: Row): Row {
  if (Number.isFinite(Number(row.change_pct))) return row
  const price = Number(row.price ?? row.close)
  const preClose = Number(row.pre_close ?? row.last_close)
  if (!Number.isFinite(price) || !Number.isFinite(preClose) || preClose === 0) return row
  return { ...row, change_pct: ((price / preClose) - 1) * 100 }
}

const categoryOptions = [
  { value: 'A', label: '沪深 A 股' }, { value: 'SH', label: '上海市场' },
  { value: 'SZ', label: '深圳市场' }, { value: 'KCB', label: '科创板' },
  { value: 'CYB', label: '创业板' }, { value: 'BJ', label: '北京市场' },
]
const sortOptions = [
  { value: 'CHANGE_PCT', label: '涨跌幅' }, { value: 'SPEED', label: '涨速' },
  { value: 'TOTAL_AMOUNT', label: '成交额' }, { value: 'TURNOVER_RATE', label: '换手率' },
  { value: 'VOLUME_RATIO', label: '量比' },
]
const marketOptions = [{ value: 'SH', label: '上海市场' }, { value: 'SZ', label: '深圳市场' }]
const strengthOptions = [
  { value: 'steady' as const, label: '中长期稳健' },
  { value: 'breakout' as const, label: '短期突破' },
  { value: 'balanced' as const, label: '多周期均衡' },
]
const universeOptions = [
  { value: 'all' as const, label: '沪深全市场' }, { value: 'sh' as const, label: '上海市场' },
  { value: 'sz' as const, label: '深圳市场' },
]
const displayRows = computed(() => {
  const normalized = tab.value === 'ranking' ? rows.value.map(withChangePct) : rows.value
  if (tab.value !== 'directory' || !directoryQuery.value.trim()) return normalized
  const query = directoryQuery.value.trim().toLowerCase()
  return normalized.filter((row) => String(row.code ?? '').includes(query) || String(row.name ?? '').toLowerCase().includes(query))
})
const stats = computed(() => {
  const pct = displayRows.value.map((row) => Number(row.change_pct)).filter(Number.isFinite)
  return {
    count: rows.value.length,
    up: pct.filter((n) => n > 0).length,
    down: pct.filter((n) => n < 0).length,
  }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = tab.value === 'ranking'
      ? await fetchMarketRanking({ category: category.value, sortType: sortType.value, count: 120 })
      : tab.value === 'stat' ? await fetchMarketStat()
        : tab.value === 'unusual' ? await fetchMarketUnusual(market.value, 100)
          : tab.value === 'directory' ? await fetchSecurityDirectory(directoryMarket.value, 0)
            : await fetchMarketStrength({ preset: strengthPreset.value, universe: strengthUniverse.value, topN: 80 })
    rows.value = response.data
    if (tab.value === 'directory') securityTotal.value = (await fetchSecurityCount(directoryMarket.value)).count
  } catch (e) {
    error.value = formatError(e)
    rows.value = []
  } finally {
    loading.value = false
  }
}

function switchTab(next: Tab) {
  tab.value = next
  void load()
}

onMounted(load)
</script>

<template>
  <div class="research-page">
    <section class="hero-strip">
      <div><span class="eyebrow">MARKET PULSE</span><h2>市场行情中心</h2><p>把排行、涨跌统计与盘中异动放在一张工作台里。</p></div>
      <div class="hero-metrics">
        <div><small>{{ tab === 'directory' ? '当前显示' : '当前记录' }}</small><strong>{{ tab === 'directory' ? displayRows.length : stats.count }}</strong></div>
        <div><small>{{ tab === 'directory' ? '市场总数' : '上涨' }}</small><strong :class="{ up: tab !== 'directory' }">{{ tab === 'directory' ? securityTotal : stats.up }}</strong></div>
        <div><small>{{ tab === 'directory' ? '数据来源' : '下跌' }}</small><strong :class="{ down: tab !== 'directory' }">{{ tab === 'directory' ? 'TDX' : stats.down }}</strong></div>
      </div>
    </section>

    <section class="control-bar">
      <div class="segmented" role="tablist">
        <button :class="{ active: tab === 'ranking' }" @click="switchTab('ranking')">行情排行</button>
        <button :class="{ active: tab === 'stat' }" @click="switchTab('stat')">涨跌统计</button>
        <button :class="{ active: tab === 'unusual' }" @click="switchTab('unusual')">盘中异动</button>
        <button :class="{ active: tab === 'directory' }" @click="switchTab('directory')">证券目录</button>
        <button :class="{ active: tab === 'strength' }" @click="switchTab('strength')">强势排名</button>
      </div>
      <div v-if="tab === 'ranking'" class="filters">
        <MacSelect v-model="category" :options="categoryOptions" aria-label="市场范围" />
        <MacSelect v-model="sortType" :options="sortOptions" aria-label="排序指标" />
      </div>
      <div v-else-if="tab === 'unusual'" class="filters one">
        <MacSelect v-model="market" :options="marketOptions" aria-label="异动市场" />
      </div>
      <div v-else-if="tab === 'directory'" class="filters directory-filters">
        <MacSelect v-model="directoryMarket" :options="marketOptions" aria-label="证券市场" />
        <input v-model="directoryQuery" type="search" placeholder="搜索代码或名称" aria-label="搜索证券" />
      </div>
      <div v-else-if="tab === 'strength'" class="filters">
        <MacSelect v-model="strengthPreset" :options="strengthOptions" aria-label="强势模式" />
        <MacSelect v-model="strengthUniverse" :options="universeOptions" aria-label="市场范围" />
      </div>
      <button class="primary query-button" :disabled="loading" @click="load">
        <svg class="button-icon" :class="{ spinning: loading }" viewBox="0 0 20 20"><path d="M10 3a7 7 0 1 1-5.2 2.3M3 3v4h4" /></svg>
        {{ loading ? '正在获取' : '刷新数据' }}
      </button>
    </section>
    <p v-if="error" class="error-banner status-banner">{{ error }}</p>
    <section class="table-panel">
      <header><div><h3>{{ tab === 'ranking' ? '实时行情排行' : tab === 'stat' ? '全市场涨跌分布' : tab === 'unusual' ? '实时异动明细' : tab === 'directory' ? '证券基础目录' : '多周期强势排名' }}</h3><p>{{ tab === 'directory' ? `市场共 ${securityTotal.toLocaleString('zh-CN')} 只 · 当前显示 ${displayRows.length} 只` : '数值统一保留至多 2 位小数' }}</p></div><span class="live-dot">{{ tab === 'directory' ? 'LIST' : tab === 'strength' ? 'LOCAL' : 'LIVE' }}</span></header>
      <DataGrid :rows="displayRows" :empty-text="loading ? '正在读取市场数据…' : '暂无符合条件的数据'" />
    </section>
  </div>
</template>

<style scoped>
.research-page{display:flex;height:100%;min-height:0;flex-direction:column;gap:14px}.hero-strip{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:18px 20px;background:linear-gradient(120deg,rgba(10,132,255,.11),rgba(94,92,230,.045) 52%,rgba(255,255,255,.02));border:1px solid var(--border);border-radius:14px}.eyebrow{color:#5cacff;font-size:9px;font-weight:750;letter-spacing:.16em}.hero-strip h2{margin-top:3px;font-size:19px;letter-spacing:-.02em}.hero-strip p{margin-top:2px;color:var(--text-dim);font-size:11px}.hero-metrics{display:flex;gap:8px}.hero-metrics>div{min-width:76px;padding:8px 10px;background:rgba(0,0,0,.16);border:1px solid var(--border);border-radius:9px}.hero-metrics small{display:block;color:var(--text-dim);font-size:9px}.hero-metrics strong{font-size:17px;font-variant-numeric:tabular-nums}.up{color:var(--up)}.down{color:var(--down)}.control-bar{display:flex;align-items:flex-end;gap:10px;padding:11px 12px;background:rgba(255,255,255,.025);border:1px solid var(--border);border-radius:12px}.segmented{display:flex;align-self:center;padding:2px;background:rgba(0,0,0,.24);border:1px solid var(--border);border-radius:9px}.segmented button{min-height:29px;padding:0 12px;background:transparent;border-color:transparent;box-shadow:none;color:var(--text-dim)}.segmented button.active{color:var(--text);background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.09);box-shadow:0 1px 4px rgba(0,0,0,.22)}.filters{display:grid;width:300px;grid-template-columns:1fr 1fr;gap:8px}.filters.one{width:150px;grid-template-columns:1fr}.query-button{min-height:34px;margin-left:auto;padding-inline:15px}.status-banner{padding:9px 12px;border-radius:9px;font-size:11px}.table-panel{display:flex;min-height:0;flex:1;flex-direction:column;padding:13px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:14px}.table-panel header{display:flex;align-items:center;justify-content:space-between;padding:0 3px 10px}.table-panel h3{font-size:13px}.table-panel p{color:var(--text-dim);font-size:10px}.live-dot{padding:2px 6px;color:var(--success);background:rgba(48,209,88,.08);border:1px solid rgba(48,209,88,.18);border-radius:5px;font-size:8px;font-weight:750;letter-spacing:.08em}@media(max-width:900px){.hero-metrics{display:none}.control-bar{flex-wrap:wrap}.filters{width:240px}.query-button{margin-left:0}}
</style>
