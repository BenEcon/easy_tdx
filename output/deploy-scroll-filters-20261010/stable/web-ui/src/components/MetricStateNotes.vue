<script setup lang="ts">
import { computed } from 'vue'
import type { MetricStates } from '../metric-state'
const props = defineProps<{ states?: MetricStates; legacy?: boolean }>()
const names: Record<string, string> = {
  total_return: '总收益率', annual_return: '年化收益', sharpe: '夏普比率', sortino: '索提诺比率',
  calmar: '卡玛比率', max_drawdown: '最大回撤', max_dd_duration: '峰值至谷底', volatility: '波动率',
  total_trades: '总交易数', win_trades: '盈利次数', lose_trades: '亏损次数', breakeven_trades: '持平次数',
  win_rate: '胜率', profit_factor: '盈亏比', avg_win: '平均盈利', avg_loss: '平均亏损',
  max_win: '最大盈利', max_loss: '最大亏损', avg_holding_days: '平均持仓天数',
}
const notes = computed(() => Object.entries(props.states ?? {})
  .filter(([key, value]) => names[key] && value.state !== 'finite'))
</script>
<template>
  <details v-if="notes.length || legacy" class="metric-notes">
    <summary>指标状态说明 <span>{{ legacy ? '历史口径' : `${notes.length} 项非有限指标` }}</span></summary>
    <p v-if="legacy">此结果未记录新版指标状态，保留原值；旧版的 0 或 999 不自动解释为不可用或无穷。需重新计算才能使用新版口径。</p>
    <template v-else>
      <p>∞ 表示分母为零的无穷比率，不代表无风险或评级满分；— 表示不可计算。持平交易单独计数，拒单不计入成交胜率。</p>
      <dl><template v-for="[key, state] in notes" :key="key"><dt>{{ names[key] }}</dt><dd>{{ state.reason }}</dd></template></dl>
    </template>
  </details>
</template>
<style scoped>
.metric-notes{margin-top:12px;padding-top:8px;border-top:1px solid var(--border);font-size:12px;color:var(--text-muted);line-height:1.7;overflow-wrap:anywhere}
summary{cursor:pointer;padding:4px 0;color:var(--text)}summary span{margin-left:10px;color:var(--text-muted);font-size:11px}
p{margin:8px 0}dl{display:grid;grid-template-columns:100px minmax(0,1fr);gap:6px 12px;margin:8px 0}dt{color:var(--text)}dd{margin:0}
@media(max-width:480px){dl{grid-template-columns:1fr;gap:3px}dd{padding:0 0 8px 12px}}
</style>
