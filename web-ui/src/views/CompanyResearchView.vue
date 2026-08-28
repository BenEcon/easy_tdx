<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import DataGrid from '../components/DataGrid.vue'
import MacSelect from '../components/MacSelect.vue'
import MarkdownContent from '../components/MarkdownContent.vue'
import StockQueryField from '../components/StockQueryField.vue'
import {
  fetchAnnouncements, fetchAuction, fetchCapitalFlow, fetchFinanceInfo,
  fetchCompanyCategories, fetchCompanyContent, fetchFinancialFiles,
  fetchCurrentFundFlow, fetchFinancialRecords, fetchFinancialReport, fetchFundFlowHistory, fetchQuote,
  fetchSymbolInfo, fetchXdxrInfo, formatError,
} from '../api'
import { detectMarket } from '../market'
import { getLastStockCode, recordStockHistory, stockDisplayName } from '../stock-history'

type Row = Record<string, unknown>
type Tab = 'overview' | 'f10' | 'flow' | 'announcements' | 'reports' | 'professional' | 'events' | 'auction'

const code = ref(getLastStockCode())
const tab = ref<Tab>('overview')
const reportType = ref<'lrb' | 'fzb' | 'llb'>('lrb')
const quoteRows = ref<Row[]>([])
const infoRows = ref<Row[]>([])
const financeRows = ref<Row[]>([])
const rows = ref<Row[]>([])
const companyCategories = ref<Row[]>([])
const selectedCategory = ref<Row | null>(null)
const companyContent = ref('')
const financialFiles = ref<Row[]>([])
const selectedFinancialFile = ref('')
const loading = ref(false)
const error = ref('')

const tabs: Array<{ value: Tab; label: string }> = [
  { value: 'overview', label: '公司概览' }, { value: 'f10', label: 'F10 资料' }, { value: 'flow', label: '资金流向' },
  { value: 'announcements', label: '公司公告' }, { value: 'reports', label: '财务报表' },
  { value: 'professional', label: '专业财务' }, { value: 'events', label: '分红送转' }, { value: 'auction', label: '集合竞价' },
]
const reportTypes = [
  { value: 'lrb' as const, label: '利润表' },
  { value: 'fzb' as const, label: '资产负债表' },
  { value: 'llb' as const, label: '现金流量表' },
]
const quote = computed(() => quoteRows.value[0] ?? infoRows.value[0] ?? {})
const displayName = computed(() => {
  const name = String(quote.value.name ?? '').trim()
  return name ? `${code.value}-${name}` : stockDisplayName(code.value)
})
const companyInitial = computed(() => {
  const name = String(quote.value.name ?? '').trim()
  return name ? name.slice(0, 1) : code.value.slice(-1)
})
const changePct = computed(() => {
  const price = Number(quote.value.price ?? quote.value.close)
  const preClose = Number(quote.value.last_close ?? quote.value.pre_close)
  return Number.isFinite(price) && Number.isFinite(preClose) && preClose !== 0 ? ((price / preClose) - 1) * 100 : null
})

function value(...keys: string[]): unknown {
  for (const key of keys) {
    if (quote.value[key] !== undefined) return quote.value[key]
  }
  return undefined
}

function numberText(input: unknown, suffix = ''): string {
  if (input === null || input === undefined || input === '') return '—'
  const number = Number(input)
  return Number.isFinite(number) ? `${number.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}${suffix}` : '—'
}

async function loadOverview(market: string) {
  const results = await Promise.allSettled([
    fetchQuote(market, code.value),
    fetchSymbolInfo(market, code.value),
    fetchFinanceInfo(market, code.value),
  ])
  quoteRows.value = results[0].status === 'fulfilled' ? results[0].value.data : []
  infoRows.value = results[1].status === 'fulfilled' ? results[1].value.data : []
  financeRows.value = results[2].status === 'fulfilled' ? results[2].value.data : []
  if (!quoteRows.value.length && !infoRows.value.length && !financeRows.value.length) {
    const failed = results.find((result) => result.status === 'rejected')
    throw failed?.status === 'rejected' ? failed.reason : new Error('未查询到公司数据')
  }
}

async function selectCompanyCategory(category: Row) {
  selectedCategory.value = category
  companyContent.value = ''
  try {
    companyContent.value = (await fetchCompanyContent(detectMarket(code.value), code.value, category)).content
  } catch (e) {
    error.value = formatError(e)
  }
}

async function loadCompanyF10(market: string) {
  companyCategories.value = (await fetchCompanyCategories(market, code.value)).data
  if (companyCategories.value.length) await selectCompanyCategory(companyCategories.value[0])
  else { selectedCategory.value = null; companyContent.value = '' }
}

async function loadProfessionalFinance() {
  if (!financialFiles.value.length) financialFiles.value = (await fetchFinancialFiles()).data
  if (!selectedFinancialFile.value && financialFiles.value.length) {
    selectedFinancialFile.value = String(financialFiles.value[0].filename ?? '')
  }
  rows.value = selectedFinancialFile.value
    ? (await fetchFinancialRecords(selectedFinancialFile.value, code.value)).data
    : []
}

async function load() {
  if (!/^\d{6}$/.test(code.value)) {
    error.value = '股票代码必须是 6 位数字'
    return
  }
  loading.value = true
  error.value = ''
  const market = detectMarket(code.value)
  try {
    if (tab.value === 'overview') await loadOverview(market)
    else if (tab.value === 'f10') await loadCompanyF10(market)
    else if (tab.value === 'flow') {
      const [capital, current, history] = await Promise.all([
        fetchCapitalFlow(market, code.value), fetchCurrentFundFlow(market, code.value), fetchFundFlowHistory(market, code.value, 100),
      ])
      rows.value = [...current.data, ...history.data, ...capital.data]
    } else if (tab.value === 'announcements') rows.value = (await fetchAnnouncements(code.value, 50)).data
    else if (tab.value === 'reports') rows.value = (await fetchFinancialReport(code.value, reportType.value, 12)).data
    else if (tab.value === 'professional') await loadProfessionalFinance()
    else if (tab.value === 'events') rows.value = (await fetchXdxrInfo(market, code.value)).data
    else rows.value = (await fetchAuction(market, code.value)).data
    recordStockHistory({ code: code.value, category: 'DAY' })
  } catch (e) {
    error.value = formatError(e)
    if (tab.value !== 'overview') rows.value = []
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
</script>

<template>
  <div class="company-page">
    <section class="query-card">
      <div class="query-title"><span>COMPANY DESK</span><h2>公司资料</h2><p>行情、资金、公告与财务信息集中查阅。</p></div>
      <StockQueryField v-model="code" @keyup.enter="load" />
      <button class="primary query-btn action-button" :disabled="loading" @click="load">
        <svg class="button-icon" :class="{ spinning: loading }" viewBox="0 0 20 20"><path d="M10 3a7 7 0 1 1-5.2 2.3M3 3v4h4" /></svg>
        {{ loading ? '查询中' : '查询公司' }}
      </button>
    </section>
    <p v-if="error" class="error-banner status-banner">{{ error }}</p>

    <section class="identity-strip">
      <div class="stock-identity"><span class="stock-logo">{{ companyInitial }}</span><div><h3>{{ displayName }}</h3><p>{{ detectMarket(code) }} · A 股</p></div></div>
      <div class="price-block"><small>最新价</small><strong>{{ numberText(value('price', 'close')) }}</strong></div>
      <div class="price-block"><small>涨跌幅</small><strong :class="changePct !== null && changePct >= 0 ? 'up' : 'down'">{{ numberText(changePct, '%') }}</strong></div>
      <div class="price-block"><small>今开 / 最高 / 最低</small><strong>{{ numberText(value('open')) }} / {{ numberText(value('high')) }} / {{ numberText(value('low')) }}</strong></div>
      <div class="price-block"><small>成交额</small><strong>{{ numberText(value('amount')) }}</strong></div>
    </section>

    <nav class="tab-bar">
      <button v-for="item in tabs" :key="item.value" :class="{ active: tab === item.value }" @click="switchTab(item.value)">{{ item.label }}</button>
      <div v-if="tab === 'reports'" class="report-select"><MacSelect v-model="reportType" :options="reportTypes" @update:model-value="load" /></div>
      <div v-else-if="tab === 'professional'" class="report-select professional-select">
        <MacSelect v-model="selectedFinancialFile" :options="financialFiles.map(file => ({ value: String(file.filename ?? ''), label: String(file.filename ?? '') }))" @update:model-value="load" />
      </div>
    </nav>

    <section v-if="tab === 'overview'" class="overview-grid">
      <div class="info-card"><header><h3>基础资料</h3><span>PROFILE</span></header><DataGrid :rows="infoRows" :empty-text="loading ? '读取基础资料…' : '暂无基础资料'" /></div>
      <div class="info-card"><header><h3>最新财务摘要</h3><span>FINANCE</span></header><DataGrid :rows="financeRows" :empty-text="loading ? '读取财务摘要…' : '暂无财务数据'" /></div>
    </section>
    <section v-else-if="tab === 'f10'" class="f10-workspace">
      <aside class="f10-index">
        <button v-for="(category, index) in companyCategories" :key="String(category.name ?? index)" :class="{ active: selectedCategory === category }" @click="selectCompanyCategory(category)">
          <span>{{ category.name ?? '未命名资料' }}</span><small>{{ Number(category.length ?? 0).toLocaleString('zh-CN') }} B</small>
        </button>
      </aside>
      <article class="f10-content">
        <header><div><h3>{{ selectedCategory?.name ?? 'F10 公司资料' }}</h3><p>已转换为适合阅读的网页格式</p></div><span>F10 · HTML</span></header>
        <MarkdownContent
          v-if="companyContent"
          :key="String(selectedCategory?.name ?? '')"
          :source="companyContent"
          :aria-label="`${selectedCategory?.name ?? 'F10 公司资料'}正文`"
        />
        <div v-else class="text-empty">{{ loading ? '正在读取公司资料…' : '暂无公司资料' }}</div>
      </article>
    </section>
    <section v-else class="content-card">
      <header><div><h3>{{ tabs.find(item => item.value === tab)?.label }}</h3><p>{{ rows.length }} 条记录 · 数据按最新时间优先</p></div><button class="sm" :disabled="loading" @click="load">刷新</button></header>
      <div v-if="tab === 'announcements' && rows.length" class="announcement-list">
        <a v-for="(row, index) in rows" :key="String(row.announcement_id ?? index)" :href="String(row.url ?? row.pdf_url ?? '#')" target="_blank" rel="noopener">
          <span class="announcement-date">{{ row.date ?? '—' }}</span><strong>{{ row.title ?? '未命名公告' }}</strong><small>{{ row.type ?? '公告' }}</small>
        </a>
      </div>
      <DataGrid v-else :rows="rows" :empty-text="loading ? '正在读取数据…' : '暂无相关数据'" />
    </section>
  </div>
</template>

<style scoped>
.company-page{display:flex;height:100%;min-height:0;flex-direction:column;gap:12px}.query-card{display:flex;align-items:flex-end;gap:11px;padding:14px 16px;background:linear-gradient(120deg,rgba(10,132,255,.085),rgba(255,255,255,.018));border:1px solid var(--border);border-radius:14px}.query-title{min-width:270px;margin-right:auto}.query-title span{color:#5cacff;font-size:9px;font-weight:750;letter-spacing:.16em}.query-title h2{margin-top:2px;font-size:18px}.query-title p{color:var(--text-dim);font-size:10px}.query-btn{min-height:36px}.status-banner{padding:8px 11px;border-radius:8px;font-size:11px}.identity-strip{display:flex;align-items:center;gap:8px;padding:11px 13px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px}.stock-identity{display:flex;min-width:220px;align-items:center;gap:10px;margin-right:auto}.stock-logo{display:grid;width:34px;height:34px;place-items:center;color:#fff;background:linear-gradient(145deg,#2997ff,#5e5ce6);border:1px solid rgba(255,255,255,.15);border-radius:9px;font-weight:700;box-shadow:0 7px 18px rgba(10,132,255,.18)}.stock-identity h3{font-size:14px}.stock-identity p{color:var(--text-dim);font-size:9px}.price-block{min-width:100px;padding:6px 10px;border-left:1px solid var(--border)}.price-block small{display:block;color:var(--text-dim);font-size:9px}.price-block strong{font-size:12px;font-variant-numeric:tabular-nums}.up{color:var(--up)}.down{color:var(--down)}.tab-bar{display:flex;align-items:center;padding:3px;overflow-x:auto;background:rgba(0,0,0,.18);border:1px solid var(--border);border-radius:10px}.tab-bar>button{min-height:30px;flex:0 0 auto;background:transparent;border-color:transparent;box-shadow:none;color:var(--text-dim)}.tab-bar>button.active{color:var(--text);background:rgba(255,255,255,.08);border-color:var(--border)}.report-select{width:140px;margin-left:auto}.professional-select{min-width:190px}.overview-grid{display:grid;min-height:0;flex:1;grid-template-columns:1fr 1fr;gap:12px}.info-card,.content-card,.f10-content{display:flex;min-height:0;flex-direction:column;padding:12px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px}.info-card header,.content-card>header,.f10-content>header{display:flex;align-items:center;justify-content:space-between;padding:0 3px 9px}.info-card h3,.content-card h3,.f10-content h3{font-size:13px}.info-card header span,.f10-content header span{color:var(--text-dim);font-size:8px;font-weight:750;letter-spacing:.08em}.content-card{flex:1}.content-card header p,.f10-content header p{color:var(--text-dim);font-size:10px}.f10-workspace{display:grid;min-height:0;flex:1;grid-template-columns:190px 1fr;gap:12px}.f10-index{padding:6px;overflow-y:auto;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px}.f10-index button{width:100%;min-height:38px;justify-content:space-between;padding:7px 9px;color:var(--text-muted);background:transparent;border-color:transparent;box-shadow:none;text-align:left}.f10-index button.active{color:var(--text);background:rgba(10,132,255,.12);border-color:rgba(10,132,255,.2)}.f10-index small{color:var(--text-dim);font-size:8px}.text-empty{display:grid;height:100%;place-items:center;color:var(--text-dim);font-size:11px}.announcement-list{height:100%;overflow:auto;border:1px solid var(--border);border-radius:11px;background:rgba(8,9,12,.3)}.announcement-list a{display:grid;grid-template-columns:88px 1fr auto;align-items:center;gap:12px;padding:10px 12px;color:var(--text-muted);border-bottom:1px solid rgba(255,255,255,.055);text-decoration:none;transition:background 130ms ease}.announcement-list a:hover{background:rgba(10,132,255,.08)}.announcement-list a:last-child{border-bottom:0}.announcement-list strong{overflow:hidden;color:var(--text);font-size:11px;font-weight:520;text-overflow:ellipsis;white-space:nowrap}.announcement-list small,.announcement-date{color:var(--text-dim);font-size:10px}@media(max-width:1000px){.query-title p{display:none}.query-title{min-width:170px}.price-block:nth-last-child(-n+2){display:none}.overview-grid{grid-template-columns:1fr}.company-page{overflow:auto}.info-card{min-height:310px}.f10-workspace{min-height:520px}}
</style>
