<script setup lang="ts">
import { computed } from 'vue'

type Row = Record<string, unknown>
type Column = { key: string; label: string }

const props = withDefaults(defineProps<{
  rows: Row[]
  columns?: Column[]
  emptyText?: string
  selectable?: boolean
}>(), {
  columns: () => [],
  emptyText: '暂无数据',
  selectable: false,
})

const emit = defineEmits<{ select: [row: Row] }>()

const LABELS: Record<string, string> = {
  code: '代码', name: '名称', market: '市场', price: '最新价', last_close: '昨收',
  pre_close: '昨收', open: '开盘', high: '最高', low: '最低', close: '收盘',
  change: '涨跌额', change_pct: '涨跌幅', speed: '涨速', vol: '成交量', volume: '成交量',
  amount: '成交额', turnover: '换手率', turnover_rate: '换手率', datetime: '时间', date: '日期',
  symbol: '代码', board_symbol: '板块代码', board_name: '板块名称', sort_value: '排序值',
  title: '公告标题', announcement_time: '公告时间', report_date: '报告期',
  time: '时间', direction: '方向', buyorsell: '买卖标记', rank: '排名',
  category: '分类', count: '数量', codes: '成分代码', filename: '文件名', filesize: '文件大小',
  desc: '说明', short_name: '简称', position: '持仓量', trade: '成交量', avg_price: '均价',
  open_interest: '持仓量', zengcang: '增仓', nature: '性质', strength: '强势分',
  ret_5: '5日涨幅', ret_20: '20日涨幅', ret_60: '60日涨幅', vol_20: '20日波动',
  annual_return: '年化收益', volatility: '年化波动', score: '风险收益分',
  weight: '建议权重', risk_contribution: '风险贡献',
  member_count: '成分数量', main_net_amount: '主力净额', main_net_3d: '3日主力净额',
  main_net_5d: '5日主力净额', observations: '有效样本', content: '内容',
  volunit: '每手股数', decimal_point: '价格精度', industry_tdx: '通达信行业',
  industry_sw: '申万行业', market_value: '总市值', circulating_value: '流通市值',
}

const hiddenKeys = new Set(['_raw', 'pdf_url', 'url', 'adj', 'market_type'])
const visibleColumns = computed<Column[]>(() => {
  if (props.columns.length) return props.columns
  const keys: string[] = []
  props.rows.slice(0, 8).forEach((row) => {
    Object.keys(row).forEach((key) => {
      if (!hiddenKeys.has(key) && !keys.includes(key)) keys.push(key)
    })
  })
  return keys.slice(0, 14).map((key) => ({ key, label: LABELS[key] ?? key }))
})

function valueClass(key: string, value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  if (/change|涨跌|speed|pct/i.test(key)) return number > 0 ? 'up' : number < 0 ? 'down' : ''
  return ''
}

function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (key === 'market' && [0, 1, 2].includes(Number(value))) {
    return ({ 0: '深圳', 1: '上海', 2: '北京' } as Record<number, string>)[Number(value)]
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—'
    const rendered = value.toLocaleString('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 0 })
    const ratioKeys = new Set(['annual_return', 'volatility', 'weight', 'risk_contribution', 'ret_5', 'ret_20', 'ret_60', 'vol_20'])
    if (ratioKeys.has(key)) return `${(value * 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`
    return /pct|涨跌幅|换手率|speed/i.test(key) ? `${rendered}%` : rendered
  }
  if (Array.isArray(value)) return value.join('、')
  return String(value)
}
</script>

<template>
  <div class="data-grid-wrap">
    <table v-if="rows.length" class="data-grid">
      <thead>
        <tr><th v-for="column in visibleColumns" :key="column.key">{{ column.label }}</th></tr>
      </thead>
      <tbody>
        <tr
          v-for="(row, index) in rows"
          :key="String(row.code ?? row.symbol ?? row.board_symbol ?? index)"
          :class="{ selectable }"
          @click="selectable && emit('select', row)"
        >
          <td v-for="column in visibleColumns" :key="column.key" :class="valueClass(column.key, row[column.key])">
            {{ formatValue(column.key, row[column.key]) }}
          </td>
        </tr>
      </tbody>
    </table>
    <div v-else class="empty-state">
      <span class="empty-orb"></span>
      <p>{{ emptyText }}</p>
    </div>
  </div>
</template>

<style scoped>
.data-grid-wrap{width:100%;height:100%;min-height:220px;overflow:auto;border:1px solid var(--border);border-radius:12px;background:rgba(8,9,12,.32)}
.data-grid{width:100%;min-width:720px;border-collapse:collapse;font-size:12px;white-space:nowrap}
th{position:sticky;top:0;z-index:1;padding:10px 12px;color:var(--text-dim);background:rgba(30,31,37,.96);border-bottom:1px solid var(--border);font-size:10px;font-weight:650;letter-spacing:.06em;text-align:right;text-transform:uppercase;backdrop-filter:blur(18px)}
th:first-child,td:first-child{text-align:left}
td{padding:9px 12px;color:var(--text-muted);border-bottom:1px solid rgba(255,255,255,.05);text-align:right;font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:0}
tbody tr{transition:background 130ms ease}
tbody tr:hover{background:rgba(255,255,255,.035)}
tbody tr.selectable{cursor:pointer}
tbody tr.selectable:hover{background:rgba(10,132,255,.09)}
td.up{color:var(--up)}td.down{color:var(--down)}
.empty-state{display:grid;min-height:220px;place-content:center;justify-items:center;gap:10px;color:var(--text-dim);font-size:12px}
.empty-orb{width:28px;height:28px;border:1px solid rgba(255,255,255,.13);border-radius:50%;background:radial-gradient(circle at 35% 30%,rgba(255,255,255,.14),transparent 45%),rgba(255,255,255,.025);box-shadow:0 8px 24px rgba(0,0,0,.2)}
</style>
