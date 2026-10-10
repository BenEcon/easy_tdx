<script setup lang="ts">
import {ref,computed} from 'vue'
import type {HorizonComparison} from '../factor-horizons'
import {factorValue} from '../factor-research'
import MacSelect from './MacSelect.vue'
const props=defineProps<{value:HorizonComparison;modelValue:number;labels:Record<string,string>}>()
const emit=defineEmits<{ 'update:modelValue':[number];'select-factor':[string] }>()
const precision=ref<'auto'|'raw'>('auto')
const display=(v:unknown,percent=false)=>factorValue(v,percent,precision.value)
const rows=computed(()=>props.value.results.flatMap(item=>item.reports.map(report=>({horizon:item.horizon,report,test:item.validation?.test_reports.find(r=>r.name===report.name)}))))
const hasTest=computed(()=>props.value.results.some(item=>item.validation))
function select(horizon:number,factor:string){emit('update:modelValue',horizon);emit('select-factor',factor)}
</script>
<template><section class="horizon-comparison" aria-label="多远期窗口对照">
  <header><h3>远期窗口对照</h3><span>同一行情 · 同一因子参数</span></header>
  <p>各窗口使用各自完整标签，有效样本可能不同；不自动选优、不反转方向。多日收益相互重叠，比较结果不等于交易策略收益。</p>
  <div class="selectors"><MacSelect :model-value="String(modelValue)" aria-label="查看远期窗口" :options="value.horizons.map(h=>({value:String(h),label:`${h} 个观测日 · 查看明细`}))" @update:model-value="emit('update:modelValue',Number($event))" /><MacSelect v-model="precision" aria-label="远期对照精度" :options="[{value:'auto',label:'易读精度'},{value:'raw',label:'原始精度'}]" /></div>
  <div class="table-scroll" tabindex="0" aria-label="远期对照汇总"><table><thead><tr><th>远期</th><th>因子</th><th>有效相关</th><th>秩相关</th><th>信息比率</th><th>高组－低组</th><th v-if="hasTest">测试有效相关</th><th v-if="hasTest">测试秩相关</th></tr></thead><tbody><tr v-for="row in rows" :key="`${row.horizon}-${row.report.name}`" :class="{selected:row.horizon===modelValue}"><th><button :aria-label="`查看${row.horizon}日${labels[row.report.name]??row.report.name}明细`" @click="select(row.horizon,row.report.name)">{{ row.horizon }} 日</button></th><th>{{ labels[row.report.name]??row.report.name }}</th><td>{{ row.report.observations }}</td><td>{{ display(row.report.rank_ic_mean) }}</td><td>{{ display(row.report.rank_ic_ir) }}</td><td>{{ display(row.report.spread,true) }}</td><td v-if="hasTest">{{ row.test?.observations??'—' }}</td><td v-if="hasTest">{{ display(row.test?.rank_ic_mean) }}</td></tr></tbody></table></div>
  <p v-if="!rows.length" role="status">所有因子均未生成结果，失败原因见研究报告；没有自动跳过失败窗口。</p>
  <p>下方明细对应 {{ modelValue }} 个观测日；切换只显示已保存结果，不重新获取行情或计算。</p>
</section></template>
<style scoped>
.horizon-comparison{min-width:0;border-block:1px solid var(--border);padding:16px 0}header{display:flex;align-items:baseline;justify-content:space-between;gap:8px;flex-wrap:wrap}h3{font-size:14px;margin:0}header span,p{font-size:11px;color:var(--text-muted)}p{line-height:1.8}.selectors{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.selectors>*{flex:1;min-width:160px}.table-scroll{overflow:auto;max-width:100%;border-block:1px solid var(--border)}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:11px}th,td{padding:10px 12px;text-align:right;font-variant-numeric:tabular-nums;border-bottom:1px solid var(--border)}th{font-weight:500;color:var(--text-muted)}th:first-child,th:nth-child(2){text-align:left}th button{font:inherit;color:inherit;background:none;border:0;padding:3px;cursor:pointer}.selected{background:rgba(10,132,255,.07)}.selected th:first-child{color:var(--accent)}.table-scroll:focus-visible{outline:2px solid var(--accent)}@media(max-width:480px){.selectors>*{min-width:100%}}
</style>
