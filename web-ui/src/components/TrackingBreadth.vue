<script setup lang="ts">
import {computed} from 'vue'
import {trackingBreadth,breadthMetrics,type TrackingAnalysis,type BreadthFilter,type BreadthMetric} from '../tracking'
import {studyLabel,type StudyPeriod} from '../research-study'
import {toggleBreadthFilter} from '../tracking-filters'
const props=defineProps<{rows:TrackingAnalysis[];periods:StudyPeriod[];modelValue:BreadthFilter[]}>()
const emit=defineEmits<{'update:modelValue':[value:BreadthFilter[]]}>()
const breadth=computed(()=>trackingBreadth(props.rows,props.periods))
const columns:Array<{label:string;metrics:BreadthMetric[]}>= [
  {label:'已覆盖 / 全部',metrics:['covered','total']},
  {label:'最近严格笔 ↑ / ↓',metrics:['penUp','penDown']},
  {label:'双线轴上 / 轴下',metrics:['aboveZero','belowZero']},
  {label:'已确认背离',metrics:['divergence']},
  {label:'结构买点 / 卖点',metrics:['buy','sell']},
  {label:'M1 买入 / 卖出提示',metrics:['macdBuy','macdSell']},
]
function active(category:StudyPeriod,metric:BreadthMetric){return props.modelValue.some(item=>item.category===category&&item.metric===metric)}
function choose(category:StudyPeriod,metric:BreadthMetric){emit('update:modelValue',toggleBreadthFilter(props.modelValue,{category,metric}))}
const missingSignals=computed(()=>props.rows.some(r=>r.study?.rows.some(p=>!p.error&&!p.buy_sell_points)))
</script>
<template><section class="tracking-breadth" aria-label="分组整体概览">
  <h3>分组整体概览</h3>
  <p>点击数字可多选，再次点击取消。同周期同列满足任一项，不同列及不同周期需同时满足；未选择时显示全部。数字始终为全组统计。</p>
  <p>每个去重标的计一次，包含板块自身；未完成周期不计入覆盖。背离按研究窗口内极值统计；买卖点按极值或确认落在窗口内统计，不代表此刻触发或仍适合买卖。M1 不等于结构一买。</p>
  <p v-if="missingSignals">部分旧记录未保存买卖点，买卖点统计仅涵盖有记录的周期；请重新分析补齐。</p>
  <div class="breadth-scroll" tabindex="0" role="region" aria-label="点击汇总数字筛选标的，可横向滚动"><table><thead><tr><th scope="col">周期</th><th v-for="c in columns" :key="c.label" scope="col">{{ c.label }}</th></tr></thead>
    <tbody><tr v-for="item in breadth" :key="item.category"><th scope="row">{{ studyLabel(item.category) }}</th><td v-for="c in columns" :key="c.label"><template v-for="(metric,index) in c.metrics" :key="metric"><span v-if="index" class="divider" aria-hidden="true">/</span><button type="button" :aria-pressed="active(item.category,metric)" :aria-label="`${studyLabel(item.category)} · ${breadthMetrics[metric]} · ${item[metric]} 个标的`" @click="choose(item.category,metric)">{{ item[metric] }}</button></template></td></tr></tbody></table></div>
  <div v-if="modelValue.length" class="filter-status"><span role="status">已选 {{ modelValue.length }} 项</span><button v-for="item in modelValue" :key="`${item.category}:${item.metric}`" type="button" :aria-label="`移除筛选：${studyLabel(item.category)} · ${breadthMetrics[item.metric]}`" @click="choose(item.category,item.metric)">{{ studyLabel(item.category) }} · {{ breadthMetrics[item.metric] }} ×</button><button type="button" @click="emit('update:modelValue',[])">清除全部筛选</button></div>
</section></template>
<style scoped>
.tracking-breadth{margin:22px 0 12px;min-width:0}h3{margin:0 0 8px;font-size:14px;font-weight:600}p{color:var(--text-muted);font-size:11px;line-height:1.8;margin:6px 0 12px}.breadth-scroll{overflow:auto;max-width:100%;scrollbar-gutter:stable}table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}thead th{font-size:11px;font-weight:500;color:var(--text-muted)}tbody th{font-weight:500}button{font:inherit;border:1px solid transparent;background:transparent;box-shadow:none;cursor:pointer;color:var(--text);border-radius:6px;min-width:32px;min-height:32px;padding:4px 7px;transition:background .15s,color .15s}button:hover,button[aria-pressed=true]{background:rgba(68,150,235,.12);color:var(--accent)}button[aria-pressed=true]{border-color:rgba(68,150,235,.3)}.divider{color:var(--text-muted);padding:0 3px}.filter-status{display:flex;align-items:center;flex-wrap:wrap;gap:12px;font-size:11px;color:var(--accent);padding-top:10px}.filter-status button{font-size:11px;color:var(--text-muted)}:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(prefers-reduced-motion:reduce){button{transition:none}}@media(max-width:640px){th,td{padding:8px}button{min-height:36px}}
</style>
