<script setup lang="ts">
import { computed, ref } from 'vue'

import ChanlunChart from '../components/ChanlunChart.vue'
import ChartFrame from '../components/ChartFrame.vue'
import MacSelect from '../components/MacSelect.vue'
import { analyzeChanlun, fetchRecentBars, formatError } from '../api'
import { detectMarket, marketLabel } from '../market'
import type { Bar, Category, ChanlunResult } from '../types'

const code = ref('000001')
const category = ref<Category>('DAY')
const count = ref(600)
const loading = ref(false)
const error = ref('')
const result = ref<ChanlunResult | null>(null)
const bars = ref<Bar[]>([])
const activeTab = ref<'structure' | 'signals' | 'divergence'>('structure')

interface LayerState {
  bis: boolean
  zss: boolean
  xds: boolean
  mmds: boolean
  bcs: boolean
}

const layers = ref<LayerState>({
  bis: true,
  zss: true,
  xds: true,
  mmds: true,
  bcs: true,
})

const layerOptions: Array<{ key: keyof LayerState; label: string }> = [
  { key: 'bis', label: '笔' },
  { key: 'zss', label: '中枢' },
  { key: 'xds', label: '线段' },
  { key: 'mmds', label: '买卖点' },
  { key: 'bcs', label: '背驰' },
]

const categories: Array<{ value: Category; label: string }> = [
  { value: 'DAY', label: '日线' },
  { value: 'WEEK', label: '周线' },
  { value: 'MONTH', label: '月线' },
  { value: 'MIN_5', label: '5 分钟' },
  { value: 'MIN_15', label: '15 分钟' },
  { value: 'MIN_30', label: '30 分钟' },
  { value: 'MIN_60', label: '60 分钟' },
]
const countOptions = [
  { value: 200, label: '200 根 · 快速', description: '适合快速查看近期结构' },
  { value: 400, label: '400 根 · 均衡', description: '速度与结构完整度平衡' },
  { value: 600, label: '600 根 · 推荐', description: '适合常规缠论分析' },
  { value: 800, label: '800 根 · 完整', description: '覆盖更长历史区间' },
]

const detectedMarket = computed(() =>
  /^\d{6}$/.test(code.value) ? marketLabel(detectMarket(code.value)) : '等待识别',
)

const summary = computed(() => {
  if (!result.value) return []
  return [
    { label: '原始 K 线', value: result.value.kline_count },
    { label: '合并 K 线', value: result.value.ckline_count },
    { label: '分型', value: result.value.fractal_count },
    { label: '笔', value: result.value.bi_count },
    { label: '中枢', value: result.value.zs_count },
    { label: '线段', value: result.value.xd_count },
    { label: '买卖点', value: result.value.mmd_count },
    { label: '背驰', value: result.value.bcs.filter((item) => item.bc).length },
  ]
})

const latestStructure = computed(() => {
  if (!result.value || result.value.bis.length === 0) return '暂无可确认结构'
  const latestBi = result.value.bis[result.value.bis.length - 1]
  const direction = latestBi.direction === 'up' ? '向上笔' : '向下笔'
  const status = latestBi.done ? '已确认' : '进行中'
  const center = result.value.zss[result.value.zss.length - 1]
  if (!center) return `当前 ${direction} · ${status}，尚未形成中枢`
  return `当前 ${direction} · ${status}，最近中枢 ${center.zd.toFixed(2)}–${center.zg.toFixed(2)}`
})

function signalLabel(type: string): string {
  const labels: Record<string, string> = {
    '1buy': '一类买点',
    '2buy': '二类买点',
    '3buy': '三类买点',
    '1sell': '一类卖点',
    '2sell': '二类卖点',
    '3sell': '三类卖点',
  }
  return labels[type] ?? type
}

function divergenceLabel(type: string): string {
  return ({ bi: '笔背驰', pz: '盘整背驰', qs: '趋势背驰' } as Record<string, string>)[type] ?? type
}

function formatMessage(text: string): string {
  return text.replace(/-?\d+\.\d+/g, (value) => Number(value).toFixed(2))
}

function segmentValue(
  segment: ChanlunResult['xds'][number],
  endpoint: 'start' | 'end',
): number {
  if (endpoint === 'start') {
    return segment.start_value ?? (segment.direction === 'up' ? segment.low : segment.high)
  }
  return segment.end_value ?? (segment.direction === 'up' ? segment.high : segment.low)
}

const segmentSequenceValid = computed(() => {
  if (!result.value) return true
  return result.value.xds.every((segment, index, segments) =>
    index === 0 || segment.start_date >= segments[index - 1]!.end_date,
  )
})

async function runAnalysis() {
  if (!/^\d{6}$/.test(code.value)) {
    error.value = '请输入 6 位证券代码'
    return
  }

  loading.value = true
  error.value = ''
  try {
    const market = detectMarket(code.value)
    const [nextBars, nextResult] = await Promise.all([
      fetchRecentBars(market, code.value, category.value, count.value),
      analyzeChanlun({ market, code: code.value, category: category.value, count: count.value }),
    ])
    bars.value = nextBars
    result.value = nextResult
    activeTab.value = 'structure'
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="chanlun-view">
    <aside class="analysis-inspector">
      <div class="inspector-title">
        <span class="inspector-symbol">⌘</span>
        <div>
          <h2>结构分析</h2>
          <p>从 K 线递进识别走势结构</p>
        </div>
      </div>

      <section class="inspector-section">
        <h3>标的与周期</h3>
        <div class="field code-field">
          <label>证券代码</label>
          <input v-model.trim="code" maxlength="6" inputmode="numeric" placeholder="000001" @keyup.enter="runAnalysis" />
          <span class="market-label">{{ detectedMarket }}</span>
        </div>
        <div class="field">
          <label>分析周期</label>
          <MacSelect v-model="category" :options="categories" aria-label="缠论分析周期" />
        </div>
        <div class="field">
          <label>历史窗口</label>
          <MacSelect v-model="count" :options="countOptions" aria-label="缠论历史窗口" />
        </div>
      </section>

      <section class="inspector-section layer-section">
        <h3>图层</h3>
        <label v-for="item in layerOptions" :key="item.key" class="layer-row">
          <span>{{ item.label }}</span>
          <input v-model="layers[item.key]" type="checkbox" />
        </label>
      </section>

      <div class="method-note">
        <strong>计算管道</strong>
        <p>K 线合并 → 分型 → 笔 → 中枢 → 线段 → 买卖点 → 背驰</p>
      </div>

      <button class="primary analyze-button" :disabled="loading" @click="runAnalysis">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? '正在解析结构…' : '开始分析' }}
      </button>
    </aside>

    <main class="analysis-workspace">
      <div v-if="error" class="error-banner">{{ error }}</div>

      <div v-if="!result && !loading" class="empty-state">
        <div class="empty-visual" aria-hidden="true">
          <span class="node n1"></span><span class="node n2"></span><span class="node n3"></span>
          <span class="node n4"></span><span class="node n5"></span>
          <svg viewBox="0 0 520 180" preserveAspectRatio="none">
            <polyline points="12,145 94,88 168,124 254,46 342,104 430,34 508,68" />
            <rect x="236" y="64" width="124" height="48" rx="8" />
          </svg>
        </div>
        <h2>观察价格如何形成结构</h2>
        <p>选择标的和周期，系统会把走势拆成笔、线段和中枢，并标出买卖点与背驰。</p>
        <button class="primary" @click="runAnalysis">分析平安银行</button>
      </div>

      <div v-else-if="loading && !result" class="loading-state">
        <span class="large-spinner"></span>
        <p>正在连接行情服务器并构建缠论结构…</p>
      </div>

      <div v-if="result" class="result-workspace" :class="{ refreshing: loading }">
        <section class="summary-strip">
          <div class="summary-context">
            <div class="summary-identity">
              <span class="symbol-name">{{ result.code }}</span>
              <span class="frequency">{{ category }}</span>
            </div>
            <div class="structure-state">
              <span class="state-dot"></span>
              <p>{{ latestStructure }}</p>
            </div>
          </div>
          <div class="summary-metrics">
            <div v-for="item in summary" :key="item.label" class="summary-item">
              <strong>{{ item.value }}</strong>
              <span>{{ item.label }}</span>
            </div>
          </div>
        </section>

        <section class="chart-workspace">
          <ChartFrame title="走势结构图" description="主副图同步缩放；下方可切换成交量、MACD、KDJ 与 RSI。">
            <template #actions>
              <div class="chart-legend">
                <span class="legend-bi">笔</span>
                <span class="legend-zs">中枢</span>
                <span class="legend-xd">线段</span>
                <span class="legend-bc">背驰</span>
              </div>
            </template>
            <ChanlunChart :bars="bars" :result="result" :layers="layers" />
          </ChartFrame>
        </section>

        <section class="detail-workspace">
          <nav class="detail-tabs" aria-label="缠论结果分类">
            <button :class="{ active: activeTab === 'structure' }" @click="activeTab = 'structure'">
              结构 <span>{{ result.bi_count + result.zs_count + result.xd_count }}</span>
            </button>
            <button :class="{ active: activeTab === 'signals' }" @click="activeTab = 'signals'">
              买卖点 <span>{{ result.mmd_count }}</span>
            </button>
            <button :class="{ active: activeTab === 'divergence' }" @click="activeTab = 'divergence'">
              背驰 <span>{{ result.bcs.filter(item => item.bc).length }}</span>
            </button>
          </nav>

          <div v-if="activeTab === 'structure'" class="structure-columns">
            <div class="data-list">
              <h4>最近的笔</h4>
              <div v-for="bi in result.bis.slice(-8).reverse()" :key="bi.index" class="data-row">
                <span class="direction" :class="bi.direction">{{ bi.direction === 'up' ? '↗' : '↘' }}</span>
                <div class="row-primary">
                  <strong>{{ bi.start_date }} → {{ bi.end_date }}</strong>
                  <small>{{ bi.direction === 'up' ? '向上笔' : '向下笔' }} · {{ bi.done ? '已确认' : '进行中' }}</small>
                </div>
                <span class="range">{{ bi.low.toFixed(2) }}–{{ bi.high.toFixed(2) }}</span>
              </div>
              <p v-if="result.bis.length === 0" class="no-data">当前窗口未形成有效笔。</p>
            </div>

            <div class="data-list">
              <h4>最近的中枢</h4>
              <div v-for="zs in result.zss.slice(-8).reverse()" :key="zs.index" class="data-row center-row">
                <span class="center-index">{{ zs.index + 1 }}</span>
                <div class="row-primary">
                  <strong>{{ zs.zd.toFixed(2) }} — {{ zs.zg.toFixed(2) }}</strong>
                  <small>{{ zs.start_date }} → {{ zs.end_date || '延续中' }}</small>
                </div>
                <span class="range">{{ zs.line_count }} 笔</span>
              </div>
              <p v-if="result.zss.length === 0" class="no-data">当前窗口尚未形成中枢。</p>
            </div>

            <section class="segment-list">
              <header>
                <div>
                  <h4>最近的线段</h4>
                  <p>端点按时间顺序连接，价格统一保留两位小数。</p>
                </div>
                <span :class="['sequence-status', { valid: segmentSequenceValid }]">
                  <i></i>{{ segmentSequenceValid ? '时间序列连续' : '检测到区间重叠' }}
                </span>
              </header>
              <div v-if="result.xds.length" class="segment-grid">
                <article
                  v-for="xd in result.xds.slice(-6).reverse()"
                  :key="xd.index"
                  class="segment-card"
                >
                  <span :class="['segment-direction', xd.direction]">
                    {{ xd.direction === 'up' ? '↗' : '↘' }}
                  </span>
                  <div>
                    <strong>线段 {{ xd.index + 1 }}</strong>
                    <small>{{ xd.start_date }} → {{ xd.end_date }}</small>
                  </div>
                  <span class="segment-price">
                    {{ segmentValue(xd, 'start').toFixed(2) }} → {{ segmentValue(xd, 'end').toFixed(2) }}
                  </span>
                </article>
              </div>
              <p v-else class="no-data">当前窗口尚未形成有效线段。</p>
            </section>
          </div>

          <div v-else-if="activeTab === 'signals'" class="event-list">
            <div v-for="(signal, index) in result.mmds.slice().reverse()" :key="`${signal.type}-${signal.date}-${index}`" class="event-row">
              <span class="event-tag" :class="signal.type.includes('buy') ? 'buy' : 'sell'">{{ signalLabel(signal.type) }}</span>
              <time>{{ signal.date || '时间未知' }}</time>
              <p>{{ formatMessage(signal.msg) }}</p>
            </div>
            <p v-if="result.mmds.length === 0" class="no-data">当前窗口没有识别到买卖点。</p>
          </div>

          <div v-else class="event-list">
            <div v-for="(bc, index) in result.bcs.filter(item => item.bc).slice().reverse()" :key="`${bc.type}-${bc.curr_date}-${index}`" class="event-row">
              <span class="event-tag divergence">{{ divergenceLabel(bc.type) }}</span>
              <time>{{ bc.curr_date || '时间未知' }}</time>
              <p>{{ formatMessage(bc.msg) }}</p>
            </div>
            <p v-if="result.bcs.filter(item => item.bc).length === 0" class="no-data">当前窗口没有确认背驰。</p>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.chanlun-view {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.analysis-inspector {
  width: 286px;
  flex: 0 0 286px;
  display: flex;
  flex-direction: column;
  padding: 16px 16px 12px;
  overflow-y: auto;
  background: rgba(25, 26, 31, 0.9);
  border-right: 1px solid var(--border);
}

.inspector-title {
  display: flex;
  align-items: center;
  gap: 11px;
  margin-bottom: 16px;
}
.inspector-symbol {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  color: #fff;
  background: var(--accent);
  border-radius: 9px;
  box-shadow: 0 6px 16px rgba(10, 132, 255, 0.22);
  font-family: var(--font-mono);
}
.inspector-title h2 { font-size: 14px; font-weight: 650; }
.inspector-title p { margin-top: 2px; color: var(--text-dim); font-size: 10px; }

.inspector-section {
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.inspector-section h3 {
  margin-bottom: 12px;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.06em;
}
.analysis-inspector .field { margin-bottom: 10px; }
.code-field { position: relative; }
.code-field input { padding-right: 68px; font-family: var(--font-mono); }
.market-label {
  position: absolute;
  right: 8px;
  bottom: 7px;
  color: var(--text-dim);
  font-size: 10px;
}

.layer-section { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }
.layer-section h3 { grid-column: 1 / -1; }
.layer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 26px;
  margin: 0;
  color: var(--text-muted);
  cursor: pointer;
}
.layer-row input {
  appearance: none;
  width: 26px;
  min-height: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: #3a3b42;
  box-shadow: none;
  transition: background-color 160ms ease;
}
.layer-row input::after {
  content: '';
  display: block;
  width: 12px;
  height: 12px;
  margin: 2px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  transition: transform 160ms ease;
}
.layer-row input:checked { background: var(--accent); }
.layer-row input:checked::after { transform: translateX(10px); }

.method-note {
  margin-top: auto;
  padding: 9px 0;
  color: var(--text-dim);
  border-top: 1px solid var(--border);
}
.method-note strong { color: var(--text-muted); font-size: 10px; font-weight: 620; }
.method-note p { margin-top: 4px; font-size: 10px; line-height: 1.45; }
.analyze-button { width: 100%; min-height: 38px; flex-shrink: 0; padding-top: 0; padding-bottom: 0; line-height: 1; }

.spinner,
.large-spinner {
  display: inline-block;
  border: 2px solid rgba(255, 255, 255, 0.28);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
.spinner { width: 12px; height: 12px; margin-right: 0; vertical-align: 0; }
.large-spinner { width: 24px; height: 24px; border-color: rgba(10,132,255,.2); border-top-color: var(--accent); }

.analysis-workspace {
  position: relative;
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  background:
    linear-gradient(rgba(255,255,255,.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px),
    var(--bg);
  background-size: 34px 34px;
}
.analysis-workspace > .error-banner { margin: 18px 20px 0; padding: 10px 13px; border-radius: var(--radius); }

.empty-state,
.loading-state {
  display: flex;
  min-height: 100%;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  padding: 40px;
  text-align: center;
}
.empty-state h2 { margin-top: 20px; font-size: 19px; font-weight: 620; letter-spacing: -0.02em; }
.empty-state > p { max-width: 430px; margin: 8px 0 18px; color: var(--text-dim); font-size: 12px; }
.empty-visual {
  position: relative;
  width: min(520px, 72%);
  height: 180px;
  opacity: 0.72;
}
.empty-visual svg { width: 100%; height: 100%; overflow: visible; }
.empty-visual polyline { fill: none; stroke: #ffd60a; stroke-width: 2; filter: drop-shadow(0 0 8px rgba(255,214,10,.16)); }
.empty-visual rect { fill: rgba(10,132,255,.12); stroke: rgba(10,132,255,.62); stroke-width: 1; }
.node { position: absolute; z-index: 1; width: 7px; height: 7px; border-radius: 50%; background: #ffd60a; box-shadow: 0 0 0 4px rgba(255,214,10,.1); }
.n1 { left: 17%; top: 46%; }.n2 { left: 32%; top: 66%; }.n3 { left: 49%; top: 22%; }.n4 { left: 66%; top: 55%; }.n5 { left: 82%; top: 15%; }
.loading-state { gap: 13px; color: var(--text-dim); font-size: 12px; }

.result-workspace {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px 20px 28px;
  transition: opacity 180ms ease;
}
.result-workspace.refreshing { opacity: 0.55; pointer-events: none; }

.summary-strip {
  display: grid;
  min-height: 112px;
  overflow: hidden;
  grid-template-columns: 272px 1fr;
  background:
    linear-gradient(135deg, rgba(10,132,255,.055), transparent 38%),
    rgba(25, 26, 31, 0.9);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 12px 34px rgba(0,0,0,.16), 0 1px 0 rgba(255,255,255,.025) inset;
}
.summary-context {
  display: flex;
  min-width: 0;
  justify-content: center;
  flex-direction: column;
  padding: 16px 18px;
  border-right: 1px solid var(--border);
}
.summary-identity { display: flex; align-items: center; }
.symbol-name { font-family: var(--font-mono); font-size: 17px; font-weight: 660; letter-spacing: -.02em; }
.frequency { margin-left: 8px; padding: 3px 7px; color: #78b8ff; background: rgba(10,132,255,.12); border: 1px solid rgba(10,132,255,.16); border-radius: 6px; font-size: 9px; }
.structure-state { display: flex; align-items: flex-start; gap: 8px; margin-top: 11px; }
.structure-state p { color: var(--text-muted); font-size: 10px; line-height: 1.5; }
.state-dot { width: 6px; height: 6px; flex: 0 0 auto; margin-top: 4px; border-radius: 50%; background: #5aa9ff; box-shadow: 0 0 0 4px rgba(10,132,255,.1); }
.summary-metrics { display: grid; grid-template-columns: repeat(4, minmax(68px, 1fr)); gap: 6px; padding: 9px; }
.summary-item { display: flex; min-height: 44px; align-items: center; justify-content: center; flex-direction: column; background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.035); border-radius: 8px; }
.summary-item strong { color: #e9e9ed; font-family: var(--font-mono); font-size: 15px; font-weight: 590; font-variant-numeric: tabular-nums; }
.summary-item span { margin-top: 2px; color: var(--text-dim); font-size: 9px; }

.chart-workspace,
.detail-workspace {
  background: rgba(22, 23, 28, 0.91);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 12px 32px rgba(0,0,0,.13);
}
.chart-workspace { padding: 14px 16px 8px; }
.section-bar { display: flex; align-items: center; justify-content: space-between; min-height: 42px; padding: 0 2px 8px; }
.section-bar h3 { font-size: 12px; font-weight: 620; }
.section-bar p { margin-top: 2px; color: var(--text-dim); font-size: 9px; }
.chart-legend { display: flex; gap: 12px; color: var(--text-dim); font-size: 9px; }
.chart-legend span::before { content: ''; display: inline-block; width: 7px; height: 7px; margin-right: 5px; border-radius: 2px; vertical-align: -1px; }
.legend-bi::before { background: #e8c75a; }.legend-zs::before { background: #4a9eff; }.legend-xd::before { background: #ad7cff; }.legend-bc::before { background: transparent; border: 1px solid #d9a3ff; transform: rotate(45deg); }

.detail-workspace { overflow: hidden; min-height: 220px; }
.detail-tabs { display: flex; align-items: center; gap: 4px; min-height: 48px; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.detail-tabs button { min-height: 30px; border-color: transparent; background: transparent; box-shadow: none; color: var(--text-dim); }
.detail-tabs button:hover { background: rgba(255,255,255,.04); color: var(--text-muted); }
.detail-tabs button.active { color: var(--text); background: rgba(255,255,255,.075); border-color: var(--border); }
.detail-tabs button span { margin-left: 5px; color: var(--text-dim); font-family: var(--font-mono); font-size: 9px; }

.structure-columns { display: grid; grid-template-columns: 1fr 1fr; }
.data-list { min-width: 0; padding: 15px 16px 18px; }
.data-list + .data-list { border-left: 1px solid var(--border); }
.data-list h4 { margin-bottom: 10px; color: var(--text-dim); font-size: 9px; font-weight: 650; letter-spacing: .06em; }
.data-row { display: flex; align-items: center; gap: 10px; min-height: 44px; border-bottom: 1px solid rgba(255,255,255,.055); }
.data-row:last-child { border-bottom: 0; }
.direction { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px; font-size: 14px; }
.direction.up { color: var(--up); background: rgba(255,94,104,.1); }.direction.down { color: var(--down); background: rgba(48,209,123,.1); }
.center-index { display: grid; place-items: center; width: 24px; height: 24px; color: #64adff; background: var(--accent-soft); border-radius: 7px; font-family: var(--font-mono); font-size: 10px; }
.row-primary { display: flex; min-width: 0; flex: 1; flex-direction: column; }
.row-primary strong { overflow: hidden; text-overflow: ellipsis; color: var(--text-muted); font-family: var(--font-mono); font-size: 10px; font-weight: 520; white-space: nowrap; }
.row-primary small { margin-top: 2px; overflow: hidden; text-overflow: ellipsis; color: var(--text-dim); font-size: 9px; white-space: nowrap; }
.range { color: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }

.segment-list { grid-column: 1 / -1; padding: 15px 16px 17px; border-top: 1px solid var(--border); }
.segment-list > header { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 11px; }
.segment-list h4 { color: var(--text-muted); font-size: 10px; font-weight: 650; letter-spacing: .04em; }
.segment-list header p { margin-top: 2px; color: var(--text-dim); font-size: 9px; }
.sequence-status { display: inline-flex; min-height: 24px; align-items: center; gap: 7px; padding: 0 9px; color: #ffb84d; background: rgba(255,159,10,.08); border: 1px solid rgba(255,159,10,.18); border-radius: 999px; font-size: 9px; white-space: nowrap; }
.sequence-status i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 3px rgba(255,159,10,.1); }
.sequence-status.valid { color: #56d98d; background: rgba(48,209,88,.07); border-color: rgba(48,209,88,.17); }
.sequence-status.valid i { box-shadow: 0 0 0 3px rgba(48,209,88,.09); }
.segment-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
.segment-card { display: grid; min-width: 0; min-height: 52px; align-items: center; grid-template-columns: 28px minmax(0,1fr) auto; gap: 9px; padding: 7px 10px; background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.045); border-radius: 9px; }
.segment-direction { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 7px; font-size: 14px; }
.segment-direction.up { color: var(--up); background: rgba(255,94,104,.09); }
.segment-direction.down { color: var(--down); background: rgba(48,209,123,.09); }
.segment-card > div { display: flex; min-width: 0; flex-direction: column; }
.segment-card strong { color: var(--text-muted); font-size: 10px; font-weight: 580; }
.segment-card small { margin-top: 2px; overflow: hidden; color: var(--text-dim); font-family: var(--font-mono); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.segment-price { color: #c8c9d0; font-family: var(--font-mono); font-size: 9px; font-variant-numeric: tabular-nums; white-space: nowrap; }

.event-list { padding: 8px 14px 16px; }
.event-row { display: grid; align-items: center; grid-template-columns: 82px 112px 1fr; gap: 12px; min-height: 48px; padding: 0 8px; border-bottom: 1px solid rgba(255,255,255,.05); transition: background-color 120ms ease; }
.event-row:hover { background: rgba(255,255,255,.022); }
.event-row:last-child { border-bottom: 0; }
.event-tag { width: fit-content; padding: 4px 8px; border: 1px solid transparent; border-radius: 999px; font-size: 9px; font-weight: 620; }
.event-tag.buy { color: #ff858d; background: rgba(255,94,104,.09); border-color: rgba(255,94,104,.13); }.event-tag.sell { color: #61dfa0; background: rgba(48,209,123,.09); border-color: rgba(48,209,123,.13); }.event-tag.divergence { color: #d9a3ff; background: rgba(191,90,242,.1); border-color: rgba(191,90,242,.14); }
.event-row time { color: var(--text-dim); font-family: var(--font-mono); font-size: 9px; }
.event-row p { color: var(--text-muted); font-size: 10px; }
.no-data { padding: 24px 0; color: var(--text-dim); font-size: 10px; text-align: center; }

@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1150px) {
  .summary-strip { grid-template-columns: 230px 1fr; }
  .segment-grid { grid-template-columns: 1fr; }
}
</style>
