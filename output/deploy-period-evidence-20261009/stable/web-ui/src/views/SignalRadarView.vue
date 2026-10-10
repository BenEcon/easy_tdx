<script setup lang="ts">
// 信号雷达页：一键扫描策略库全部已保存策略（单标的/多标的/多策略组合），
// 把每种策略展开成"策略×标的"子任务，用最近 N 根 K 线（窗口可选，默认 5）
// 判断买/卖信号并汇总列出——方便每天跟踪"今天哪些策略有信号"。
// 后端 POST /backtest/signal-scan/run/async；取行情在提交请求内完成（标的多时
// 提交本身就要等一会儿），结果轮询拿 SignalScanResult。上次扫描结果缓存在
// localStorage，进页面先展示，避免每次都要重扫。

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import MacSelect from '../components/MacSelect.vue'
import AdjustPicker from '../components/AdjustPicker.vue'
import { asSignalScanResult, formatError, runSignalScanWithPolling } from '../api'
import type { SignalScanResult, SignalScanRow } from '../types'
import { useMarketPreferences } from '../market-preferences'

const router = useRouter()
const { adjustMode } = useMarketPreferences()

const WINDOW_OPTIONS = [1, 3, 5, 10]
const WINDOW_SELECT_OPTIONS = WINDOW_OPTIONS.map((value) => ({ value, label: `窗口 · ${value} 根` }))
const STORAGE_KEY = 'easy-tdx.signal-radar.last'

const windowBars = ref(5)
const scanning = ref(false)
const error = ref('')
const result = ref<SignalScanResult | null>(null)
const scannedAt = ref('') // 本地时间戳（上次扫描完成时刻）
const elapsedSec = ref('') // 上次扫描总耗时（提交+计算）

interface CachedScan {
  result: SignalScanResult
  scannedAt: string
  windowBars: number
}

onMounted(() => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const cached = JSON.parse(raw) as CachedScan
    if (cached?.result?.rows) {
      result.value = cached.result
      scannedAt.value = cached.scannedAt || ''
      if (WINDOW_OPTIONS.includes(cached.windowBars)) windowBars.value = cached.windowBars
    }
  } catch {
    // 缓存损坏则忽略，直接空态
  }
})

async function onScan() {
  if (scanning.value) return
  scanning.value = true
  error.value = ''
  const t0 = Date.now()
  try {
    const state = await runSignalScanWithPolling({
      window_bars: windowBars.value,
      adjust: adjustMode.value,
    })
    result.value = asSignalScanResult(state)
    scannedAt.value = new Date().toLocaleString('zh-CN', { hour12: false })
    elapsedSec.value = ((Date.now() - t0) / 1000).toFixed(1)
    const cached: CachedScan = {
      result: result.value,
      scannedAt: scannedAt.value,
      windowBars: windowBars.value,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cached))
  } catch (e) {
    error.value = formatError(e)
  } finally {
    scanning.value = false
  }
}

// ── 筛选 ─────────────────────────────────────────────────────────────────────

type FilterKey = 'signal' | 'buy' | 'sell' | 'error' | 'all'

const activeFilter = ref<FilterKey>('signal') // 默认只看有信号的

function hasBuy(r: SignalScanRow): boolean {
  return r.recent_signals.some((s) => s.direction === 'BUY')
}
function hasSell(r: SignalScanRow): boolean {
  return r.recent_signals.some((s) => s.direction === 'SELL')
}

const filterDefs = computed(() => {
  const rows = result.value?.rows || []
  const defs: { key: FilterKey; label: string; count: number }[] = [
    { key: 'signal', label: '有信号', count: rows.filter((r) => !r.error && r.recent_signals.length > 0).length },
    { key: 'buy', label: '买入', count: rows.filter((r) => !r.error && hasBuy(r)).length },
    { key: 'sell', label: '卖出', count: rows.filter((r) => !r.error && hasSell(r)).length },
    { key: 'error', label: '失败', count: rows.filter((r) => r.error).length },
    { key: 'all', label: '全部', count: rows.length },
  ]
  return defs
})

const visibleRows = computed(() => {
  const rows = result.value?.rows || []
  switch (activeFilter.value) {
    case 'signal':
      return rows.filter((r) => !r.error && r.recent_signals.length > 0)
    case 'buy':
      return rows.filter((r) => !r.error && hasBuy(r))
    case 'sell':
      return rows.filter((r) => !r.error && hasSell(r))
    case 'error':
      return rows.filter((r) => r.error)
    default:
      return rows
  }
})

// ── 展示辅助 ─────────────────────────────────────────────────────────────────

function kindLabel(kind: SignalScanRow['kind']): string {
  return kind === 'multi' ? '多策略' : kind === 'portfolio' ? '多标的' : '单标的'
}

function parameterSummary(params: SignalScanRow['params']): string {
  const entries = Object.entries(params)
  if (entries.length === 0) return '无额外参数'
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(' · ')
}

function reviewStartDate(endDate: string): string {
  const date = new Date(`${endDate}T00:00:00`)
  if (Number.isNaN(date.getTime())) return '2020-01-06'
  date.setFullYear(date.getFullYear() - 2)
  return date.toISOString().slice(0, 10)
}

/** 打开信号对应的研究页，并还原扫描时的标的、策略与参数供人工复核。 */
function onReview(r: SignalScanRow, selectedSignal?: SignalScanRow['recent_signals'][number]) {
  const codeOnly = r.symbol.includes(':') ? r.symbol.split(':').pop()! : r.symbol
  const endDate = (r.last_bar_date || new Date().toISOString()).slice(0, 10)
  const reviewQuery = {
    review: 'signal',
    autoRun: '1',
    symbol: codeOnly || undefined,
    category: r.category || undefined,
    signal: selectedSignal?.direction || r.latest_signal || undefined,
    signalDate: selectedSignal?.date || r.signal_date || undefined,
    strategyName: r.strategy_name,
    strategyLabel: r.strategy_label || r.strategy,
  }

  if (r.strategy === 'chanlun_mmd') {
    router.push({
      path: '/chanlun',
      query: { ...reviewQuery, count: '800' },
    })
    return
  }

  router.push({
    path: '/',
    query: {
      ...reviewQuery,
      strategy: r.strategy,
      params: JSON.stringify(r.params),
      startDate: reviewStartDate(endDate),
      endDate,
    },
  })
}

/** 打开可编辑的策略配置；单标的策略保存时覆盖原记录，组合子策略保存为独立策略。 */
function onModify(r: SignalScanRow) {
  const codeOnly = r.symbol.includes(':') ? r.symbol.split(':').pop()! : r.symbol
  const endDate = (r.last_bar_date || new Date().toISOString()).slice(0, 10)
  router.push({
    path: '/',
    query: {
      strategy: r.strategy,
      params: JSON.stringify(r.params),
      symbol: codeOnly || undefined,
      category: r.category || undefined,
      startDate: reviewStartDate(endDate),
      endDate,
      editStrategyId: r.kind === 'single' ? r.strategy_id : undefined,
      editMode: r.kind === 'single' ? 'update' : 'copy',
      strategyName: r.strategy_name,
      strategyLabel: r.strategy_label || r.strategy,
    },
  })
}
</script>

<template>
  <div class="radar-view">
    <header class="page-header">
      <div>
        <h2>信号雷达</h2>
        <p class="subtitle">
          一键扫描策略库全部已保存策略，列出最近 K 线内出现买入/卖出信号的策略。
          <template v-if="scannedAt">
            上次扫描 {{ scannedAt }}<template v-if="elapsedSec">（{{ elapsedSec }}s）</template>。
          </template>
        </p>
      </div>
      <div class="header-actions">
        <AdjustPicker compact />
        <div class="window-picker">
          <MacSelect
            v-model="windowBars"
            :options="WINDOW_SELECT_OPTIONS"
            :disabled="scanning"
            aria-label="信号扫描窗口"
          />
        </div>
        <button class="primary action-button" :disabled="scanning" @click="onScan">
          <svg v-if="!scanning" class="button-icon" viewBox="0 0 20 20" aria-hidden="true">
            <path d="m11.5 2.5-6 9h4l-1 6 6-9h-4z" />
          </svg>
          <span>{{ scanning ? '扫描中…' : '一键扫描' }}</span>
        </button>
      </div>
    </header>

    <div v-if="error" class="error-banner">⚠ {{ error }}</div>

    <!-- 扫描中：提交请求内要逐标的取行情，需要等待 -->
    <div v-if="scanning" class="scanning-box">
      <span class="spinner"></span>
      正在扫描：逐标的取最近 800 根 K 线并计算信号（标的较多时约需几十秒，请稍候）…
    </div>

    <template v-if="result && !scanning">
      <!-- 汇总卡片 -->
      <div class="stat-cards">
        <div class="stat">
          <span class="k">子任务</span>
          <span class="v">{{ result.total }}</span>
        </div>
        <div class="stat">
          <span class="k">买入信号</span>
          <span class="v buy">{{ result.buy_count }}</span>
        </div>
        <div class="stat">
          <span class="k">卖出信号</span>
          <span class="v sell">{{ result.sell_count }}</span>
        </div>
        <div class="stat">
          <span class="k">失败</span>
          <span class="v dim">{{ result.error_count }}</span>
        </div>
      </div>

      <p class="hint">
        窗口 = 最近 {{ windowBars }} 根 {{ result.rows[0]?.category === 'DAY' ? '交易日' : 'K 线' }}；
        盘中最后一根 K 线未收盘，信号为盘中即时值，收盘后为准。
      </p>

      <!-- 筛选 tab -->
      <nav class="tabs">
        <button
          v-for="f in filterDefs"
          :key="f.key"
          :class="['tab', { active: activeFilter === f.key }]"
          @click="activeFilter = f.key"
        >
          {{ f.label }}<span class="tab-count">{{ f.count }}</span>
        </button>
      </nav>

      <div v-if="visibleRows.length === 0" class="placeholder">
        <p>{{ activeFilter === 'signal' ? '窗口内没有任何买卖信号。' : '该筛选下没有子任务。' }}</p>
        <p class="hint">可切换更大的窗口（如 10 根）或点「一键扫描」重新检查。</p>
      </div>

      <div v-else class="radar-table-shell">
      <table class="radar-table">
        <thead>
          <tr>
            <th>策略</th>
            <th>类型</th>
            <th>子策略</th>
            <th>标的</th>
            <th>最新信号</th>
            <th>窗口内信号</th>
            <th class="num">最新收盘</th>
            <th>仓位</th>
            <th class="review-heading">策略操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(r, i) in visibleRows"
            :key="`${r.strategy_id}-${i}`"
            :class="{ errored: r.error }"
            :data-signal="r.latest_signal || undefined"
          >
            <td class="name" :title="r.strategy_name">
              <span class="strategy-marker" aria-hidden="true"></span>
              <span class="strategy-row-name">{{ r.strategy_name }}</span>
            </td>
            <td><span class="kind-badge" :class="r.kind">{{ kindLabel(r.kind) }}</span></td>
            <td
              class="sub-strat"
              tabindex="0"
              :aria-label="`${r.strategy_label || r.strategy}；参数：${parameterSummary(r.params)}`"
            >
              <span class="strategy-name-text">{{ r.strategy_label || r.strategy }}</span>
              <span class="params-tooltip" role="tooltip">
                <small>策略参数</small>
                {{ parameterSummary(r.params) }}
              </span>
            </td>
            <td class="sym"><span class="symbol-code">{{ r.symbol }}</span></td>
            <td v-if="r.error" class="err" colspan="4">⚠ {{ r.error }}</td>
            <template v-else>
              <td>
                <span v-if="r.latest_signal" class="signal-tag" :class="r.latest_signal">
                  {{ r.latest_signal === 'BUY' ? '买入' : '卖出' }}
                </span>
                <span v-else class="none-tag">—</span>
              </td>
              <td class="seq">
                <div v-if="r.recent_signals.length" class="signal-links">
                  <button
                    v-for="signal in r.recent_signals"
                    :key="`${signal.direction}-${signal.date}`"
                    :class="['signal-link', signal.direction]"
                    :title="`复核 ${signal.date} ${signal.direction === 'BUY' ? '买入' : '卖出'}信号`"
                    @click="onReview(r, signal)"
                  >
                    <span class="signal-direction">
                      <i></i>{{ signal.direction === 'BUY' ? '买入' : '卖出' }}
                    </span>
                    <time>{{ signal.date.slice(5, 10) }}</time>
                  </button>
                </div>
                <span v-else>—</span>
              </td>
              <td class="num"><strong class="close-value">{{ r.last_close != null ? r.last_close.toFixed(2) : '-' }}</strong></td>
              <td>
                <span v-if="r.position" class="pos-tag" :class="r.position">
                  {{ r.position === 'holding' ? '持仓' : '空仓' }}
                </span>
                <span v-else class="none-tag">—</span>
              </td>
            </template>
            <td class="review-cell">
              <div v-if="!r.error" class="strategy-actions">
                <button class="review-button modify-button" title="修改策略参数" @click="onModify(r)">
                  <svg viewBox="0 0 20 20" aria-hidden="true">
                    <path d="m4 14.8.5-3.2L12.2 4l2.8 2.8-7.7 7.6zM10.8 5.4l2.8 2.8M4 16h12" />
                  </svg>
                  <span>修改策略</span>
                </button>
                <button class="review-button" @click="onReview(r)">
                  <svg viewBox="0 0 20 20" aria-hidden="true">
                    <circle cx="8.5" cy="8.5" r="4.75" />
                    <path d="m12.1 12.1 3.4 3.4M6.4 8.7l1.3 1.3 2.8-3" />
                  </svg>
                  <span>{{ r.recent_signals.length ? '复核信号' : '查看策略' }}</span>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </template>

    <div v-if="!result && !scanning && !error" class="placeholder">
      <p>还没有扫描结果。</p>
      <p class="hint">
        点右上角「⚡ 一键扫描」，把策略库里保存的单策略与组合策略全部检查一遍，
        列出最近 {{ windowBars }} 根 K 线内出现买卖信号的策略。每天收盘后扫一次即可跟踪。
      </p>
    </div>
  </div>
</template>

<style scoped>
.radar-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px 20px 32px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 16px;
  font-weight: 600;
}
.subtitle {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 4px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  flex-wrap: nowrap;
}
.header-actions :deep(.mac-select-trigger) {
  height: 34px;
  min-height: 34px;
  padding-top: 0;
  padding-bottom: 0;
  line-height: 1;
}
.window-picker {
  display: flex;
  align-items: center;
  flex: 0 0 auto;
  white-space: nowrap;
}
.window-picker :deep(.mac-select) { width: 118px; }
.primary {
  min-height: 34px;
  padding: 0 12px;
  font-size: 11px;
  background: linear-gradient(180deg, rgba(38,143,247,.2), rgba(10,112,214,.14));
  border: 1px solid rgba(82,168,255,.34);
  color: #b9dcff;
  font-weight: 620;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 1px 0 rgba(255,255,255,.055) inset;
}
.primary:hover:not(:disabled) {
  color: #e2f1ff;
  background: linear-gradient(180deg, rgba(45,151,255,.29), rgba(10,116,222,.2));
  border-color: rgba(93,176,255,.5);
}
.primary:disabled {
  opacity: 0.6;
  cursor: default;
}
.error-banner {
  background: rgba(239, 65, 70, 0.12);
  border: 1px solid var(--up);
  color: var(--up);
  padding: 10px 14px;
  border-radius: var(--radius);
  margin-bottom: 16px;
  font-size: 13px;
}
.scanning-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 13px;
}
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 50%;
  color: var(--text-dim);
  gap: 8px;
}
.placeholder .hint,
.hint {
  font-size: 12px;
  color: var(--text-dim);
  max-width: 560px;
  line-height: 1.6;
}

/* 汇总卡片 */
.stat-cards {
  display: flex;
  gap: 14px;
  margin-bottom: 10px;
}
.stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
}
.stat .k {
  font-size: 12px;
  color: var(--text-dim);
}
.stat .v {
  font-size: 22px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.stat .v.buy {
  color: var(--up);
}
.stat .v.sell {
  color: var(--down);
}
.stat .v.dim {
  color: var(--text-dim);
}

/* 筛选 tab（与策略库页同风格） */
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  margin: 14px 0 12px;
}
.tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab:hover {
  color: var(--text);
}
.tab.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.tab-count {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--border);
  color: var(--text-dim);
  font-weight: 400;
}
.tab.active .tab-count {
  background: rgba(74, 158, 255, 0.18);
  color: var(--accent);
}

/* 结果表 */
.radar-table-shell {
  width: 100%;
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 255, 255, .14) transparent;
}
.radar-table {
  width: 100%;
  min-width: 1080px;
  border-collapse: separate;
  border-spacing: 0 6px;
  font-size: 13px;
}
.radar-table th {
  padding: 3px 12px 6px;
  text-align: left;
  vertical-align: middle;
  color: var(--text-dim);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: .045em;
  white-space: nowrap;
}
.radar-table tbody td {
  height: 48px;
  padding: 8px 12px;
  text-align: left;
  vertical-align: middle;
  background: color-mix(in srgb, var(--bg-panel) 72%, transparent);
  border-top: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  transition: background .16s ease, border-color .16s ease, box-shadow .16s ease;
}
.radar-table tbody td:first-child {
  border-left: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  border-radius: 10px 0 0 10px;
}
.radar-table tbody td:last-child {
  border-right: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
  border-radius: 0 10px 10px 0;
}
.radar-table tbody tr:hover td {
  background: color-mix(in srgb, var(--bg-panel) 88%, rgba(255, 255, 255, .025));
  border-color: color-mix(in srgb, var(--accent) 18%, var(--border));
  box-shadow: inset 0 1px rgba(255, 255, 255, .018), 0 5px 18px rgba(0, 0, 0, .08);
}
.radar-table .num {
  text-align: right;
  font-family: var(--font-mono);
}
.radar-table .name {
  width: 190px;
  max-width: 190px;
  white-space: nowrap;
}
.strategy-marker {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 9px;
  vertical-align: 1px;
  background: color-mix(in srgb, var(--text-dim) 58%, transparent);
  border-radius: 50%;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--text-dim) 8%, transparent);
}
.radar-table tr[data-signal="BUY"] .strategy-marker {
  background: color-mix(in srgb, var(--up) 82%, white);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--up) 10%, transparent);
}
.radar-table tr[data-signal="SELL"] .strategy-marker {
  background: color-mix(in srgb, var(--down) 82%, white);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--down) 10%, transparent);
}
.strategy-row-name {
  display: inline-block;
  max-width: calc(100% - 22px);
  overflow: hidden;
  color: var(--text);
  font-weight: 620;
  line-height: 1.2;
  text-overflow: ellipsis;
  vertical-align: middle;
}
.radar-table .sym {
  white-space: nowrap;
}
.symbol-code {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 0 7px;
  color: color-mix(in srgb, var(--text) 88%, var(--text-muted));
  background: rgba(255, 255, 255, .028);
  border: 1px solid rgba(255, 255, 255, .055);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: .025em;
}
.close-value {
  color: var(--text);
  font-size: 12px;
  font-weight: 650;
}
.radar-table .sub-strat {
  position: relative;
  width: 190px;
  max-width: 190px;
  white-space: nowrap;
  outline: none;
}
.strategy-name-text {
  display: block;
  overflow: hidden;
  color: var(--text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.params-tooltip {
  position: absolute;
  z-index: 30;
  top: calc(100% - 2px);
  left: 8px;
  display: block;
  width: max-content;
  max-width: min(420px, 46vw);
  padding: 8px 10px;
  color: #c8ccd4;
  background: rgba(22, 24, 29, .97);
  border: 1px solid rgba(255, 255, 255, .12);
  border-radius: 8px;
  box-shadow: 0 12px 30px rgba(0, 0, 0, .34), inset 0 1px rgba(255, 255, 255, .035);
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.55;
  white-space: normal;
  pointer-events: none;
  opacity: 0;
  transform: translateY(-3px) scale(.985);
  transform-origin: top left;
  transition: opacity .14s ease, transform .14s ease;
}
.params-tooltip small {
  display: block;
  margin-bottom: 3px;
  color: #7fafd5;
  font-family: inherit;
  font-size: 8px;
  font-weight: 650;
  letter-spacing: .1em;
}
.sub-strat:hover .params-tooltip,
.sub-strat:focus-visible .params-tooltip {
  z-index: 50;
  opacity: 1;
  transform: translateY(0) scale(1);
}
.sub-strat:hover,
.sub-strat:focus-within { z-index: 40; }
.sub-strat:focus-visible .strategy-name-text {
  color: var(--text);
}
.radar-table .seq {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}
.signal-links {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}
.signal-link {
  display: inline-flex;
  min-height: 26px;
  align-items: center;
  gap: 6px;
  padding: 0 7px 0 6px;
  color: var(--text-muted);
  background: linear-gradient(180deg, rgba(255, 255, 255, .035), rgba(255, 255, 255, .012));
  border: 1px solid rgba(255, 255, 255, .075);
  border-radius: 7px;
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1;
  cursor: pointer;
  box-shadow: inset 0 1px rgba(255, 255, 255, .025);
  transition: color .15s ease, border-color .15s ease, background .15s ease, box-shadow .15s ease, transform .15s ease;
}
.signal-direction { display: inline-flex; align-items: center; gap: 4px; font-family: inherit; font-weight: 650; }
.signal-direction i {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  background: currentColor;
  border-radius: 50%;
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 10%, transparent);
}
.signal-link time {
  padding-left: 6px;
  color: var(--text-dim);
  border-left: 1px solid rgba(255, 255, 255, .075);
  font: inherit;
  letter-spacing: .02em;
}
.signal-link.BUY {
  color: color-mix(in srgb, var(--up) 76%, #d7d9df);
  background: linear-gradient(180deg, color-mix(in srgb, var(--up) 8%, transparent), rgba(255, 255, 255, .012));
  border-color: color-mix(in srgb, var(--up) 18%, rgba(255, 255, 255, .06));
}
.signal-link.SELL {
  color: color-mix(in srgb, var(--down) 76%, #d7d9df);
  background: linear-gradient(180deg, color-mix(in srgb, var(--down) 8%, transparent), rgba(255, 255, 255, .012));
  border-color: color-mix(in srgb, var(--down) 18%, rgba(255, 255, 255, .06));
}
.signal-link:hover {
  transform: translateY(-1px);
  box-shadow: 0 5px 14px rgba(0, 0, 0, .18), inset 0 1px rgba(255, 255, 255, .04);
}
.signal-link.BUY:hover { color: var(--up); border-color: color-mix(in srgb, var(--up) 40%, transparent); background: color-mix(in srgb, var(--up) 10%, rgba(255, 255, 255, .01)); }
.signal-link.SELL:hover { color: var(--down); border-color: color-mix(in srgb, var(--down) 40%, transparent); background: color-mix(in srgb, var(--down) 10%, rgba(255, 255, 255, .01)); }
.signal-link:focus-visible { outline: none; box-shadow: 0 0 0 3px rgba(10, 132, 255, .15); border-color: rgba(10, 132, 255, .65); }
.radar-table .err {
  color: var(--up);
  font-size: 12px;
  line-height: 1.45;
}
.radar-table tr.errored td {
  background: color-mix(in srgb, var(--up) 3%, var(--bg-panel));
}
.radar-table tr.errored .strategy-marker {
  background: var(--up);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--up) 10%, transparent);
}
.review-heading,
.review-cell {
  text-align: right !important;
  white-space: nowrap;
}
.strategy-actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  opacity: .86;
  transition: opacity .16s ease;
}
.radar-table tbody tr:hover .strategy-actions { opacity: 1; }
.review-button {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 9px;
  color: #a9d3f8;
  background: linear-gradient(180deg, rgba(62, 142, 211, .12), rgba(42, 104, 160, .08));
  border: 1px solid rgba(105, 174, 230, .25);
  border-radius: 7px;
  font-size: 11px;
  font-weight: 590;
  line-height: 1;
  cursor: pointer;
  box-shadow: inset 0 1px rgba(255, 255, 255, .035);
  transition: color .16s ease, border-color .16s ease, background .16s ease, transform .16s ease;
}
.review-button svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.55;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.review-button:hover {
  color: #d8ecff;
  border-color: rgba(113, 187, 247, .45);
  background: linear-gradient(180deg, rgba(70, 153, 224, .2), rgba(42, 104, 160, .12));
  transform: translateY(-1px);
}
.modify-button {
  color: var(--text-muted);
  background: rgba(255, 255, 255, .025);
  border-color: var(--border);
}
.modify-button:hover {
  color: #d2d5dc;
  border-color: rgba(190, 195, 205, .25);
  background: rgba(255, 255, 255, .05);
}

/* 徽章 */
.kind-badge {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 0 8px;
  border: 1px solid rgba(74, 158, 255, .12);
  border-radius: 7px;
  font-size: 10px;
  font-weight: 620;
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent);
  white-space: nowrap;
}
.kind-badge.portfolio {
  background: rgba(140, 110, 220, 0.18);
  border-color: rgba(140, 110, 220, .16);
  color: #b39ddb;
}
.kind-badge.multi {
  background: rgba(245, 158, 11, 0.18);
  border-color: rgba(245, 158, 11, .16);
  color: #f59e0b;
}
.signal-tag {
  display: inline-flex;
  min-width: 48px;
  min-height: 24px;
  align-items: center;
  justify-content: center;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 7px;
  font-size: 10px;
  font-weight: 650;
  white-space: nowrap;
}
/* A股习惯：买入红、卖出绿 */
.signal-tag.BUY {
  background: rgba(239, 65, 70, 0.14);
  border-color: rgba(239, 65, 70, .13);
  color: var(--up);
}
.signal-tag.SELL {
  background: rgba(24, 160, 88, 0.16);
  border-color: rgba(24, 160, 88, .14);
  color: var(--down);
}
.none-tag {
  color: var(--text-dim);
}
.pos-tag {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 7px;
  font-size: 10px;
  font-weight: 620;
  white-space: nowrap;
}
.pos-tag.holding {
  background: rgba(239, 65, 70, 0.12);
  border-color: rgba(239, 65, 70, .12);
  color: var(--up);
}
.pos-tag.flat {
  background: rgba(255, 255, 255, .035);
  border-color: rgba(255, 255, 255, .055);
  color: var(--text-dim);
}
.ghost {
  font-size: 12px;
  padding: 4px 12px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.ghost:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.sm {
  font-size: 12px;
  padding: 4px 12px;
}
</style>
