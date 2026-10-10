<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {FactorValidationResult} from '../factor-validation'
import {factorValue} from '../factor-research'
import MacSelect from './MacSelect.vue'
import ChartFrame from './ChartFrame.vue'
import FactorDiagnosticChart from './FactorDiagnosticChart.vue'
import DataGrid from './DataGrid.vue'
const props=defineProps<{value:FactorValidationResult;labels:Record<string,string>;factor?:string}>()
const foldKey=ref('1'),focus=ref('')
watch(()=>props.factor,value=>{focus.value=value??''},{immediate:true})
const precision=ref<'auto'|'raw'>('auto')
const display=(v:unknown,percent=false)=>factorValue(v,percent,precision.value)
const fold=computed(()=>props.value.folds.find(f=>String(f.id)===foldKey.value)??props.value.folds[0])
const active=computed(()=>props.value.test_reports.find(r=>r.name===focus.value)??props.value.test_reports[0])
const rows=computed(()=>fold.value?.phases.map(p=>({phase:p,report:p.reports.find(r=>r.name===active.value?.name)}))??[])
const label=(key:string)=>props.labels[key]??key
const phaseLabel={train:'训练区间',validation:'验证区间',test:'测试区间'}
</script>
<template><section class="time-validation" aria-label="时间外检验结果">
  <header><h3>{{ value.config.mode==='walk_forward'?'滚动向前检验':'训练／验证／测试' }}</h3><span>固定参数 · {{ value.folds.length }} 个窗口</span></header>
  <p>全样本统计见下方；这里仅汇总各区间内部已完成的远期标签，不自动选择最佳参数或因子方向。</p>
  <div class="selectors"><MacSelect :model-value="String(fold?.id??1)" aria-label="检验窗口" :options="value.folds.map(f=>({value:String(f.id),label:`窗口 ${f.id} · ${f.phases[2]?.start} — ${f.phases[2]?.end}`}))" @update:model-value="foldKey=$event" /><MacSelect v-if="active" :model-value="active.name" aria-label="时间检验因子" :options="value.test_reports.map(r=>({value:r.name,label:label(r.name)}))" @update:model-value="focus=$event" /><MacSelect v-model="precision" aria-label="时间检验精度" :options="[{value:'auto',label:'易读精度'},{value:'raw',label:'原始精度'}]" /></div>
  <p v-if="!active" role="status">所选因子均未生成结果，失败原因保留在研究报告中。</p>
  <div class="table-scroll" tabindex="0" aria-label="分区检验汇总"><table><thead><tr><th>区间</th><th>实际起止日期</th><th>日期数</th><th>边界剔除</th><th>有效相关</th><th>秩相关</th><th>信息比率</th><th>高组－低组</th></tr></thead><tbody><tr v-for="row in rows" :key="row.phase.phase"><th>{{ phaseLabel[row.phase.phase] }}<small v-if="row.phase.partial">末尾不足一窗</small></th><td>{{ row.phase.start }} — {{ row.phase.end }}</td><td>{{ row.phase.date_count }}</td><td>{{ row.phase.purged_dates }}</td><td>{{ row.report?.observations??'—' }}</td><td>{{ display(row.report?.rank_ic_mean) }}</td><td>{{ display(row.report?.rank_ic_ir) }}</td><td>{{ display(row.report?.spread,true) }}</td></tr></tbody></table></div>
  <details><summary>当前窗口各区间诊断</summary><div v-for="row in rows" :key="row.phase.phase"><h4>{{ phaseLabel[row.phase.phase] }}</h4><p v-for="(n,reason) in row.report?.diagnostics" :key="reason">{{ reason }}：{{ n }} 个观测日</p><p>原始因子值覆盖率 {{ display(row.report?.coverage,true) }}，可容纳完整标签的日期 {{ row.phase.label_eligible_dates }} 个。</p></div></details>
  <template v-if="active">
    <p>全部测试窗口 · {{ active.daily.length }} 个观测日 · {{ active.observations }} 个有效相关截面。按逐日观测汇总，不平均各窗口的平均值。</p>
    <ChartFrame title="测试区间秩相关" description="边界剔除和缺失保留断点；不以全样本曲线替代"><FactorDiagnosticChart correlation :precision="precision" :labels="active.daily.map(d=>d.date)" :series="[{name:'测试秩相关',values:active.daily.map(d=>d.rank_ic)}]" /></ChartFrame>
    <details :open="active.observations===0"><summary>测试期未参与统计的原因</summary><p v-if="active.observations===0">没有有效相关截面，不代表零相关或检验成功。</p><p v-for="(n,reason) in active.diagnostics" :key="reason">{{ reason }}：{{ n }} 个观测日</p></details>
    <details><summary>测试期逐日明细</summary><DataGrid :rows="active.daily.map(d=>({...d,ic:display(d.ic),rank_ic:display(d.rank_ic)}))" :columns="[{key:'date',label:'信号日'},{key:'label_end',label:'收益终点'},{key:'fold',label:'窗口'},{key:'n',label:'有效标的'},{key:'ic',label:'线性相关'},{key:'rank_ic',label:'秩相关'},{key:'reason',label:'未参与原因'}]" /></details>
  </template>
  <details><summary>时间划分口径与限制</summary><p v-for="note in value.limitations" :key="note">{{ note }}</p><p>版本：{{ value.version }}</p></details>
</section></template>
<style scoped>
.time-validation{min-width:0;border-block:1px solid var(--border);padding:18px 0}header{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px}h3{font-size:14px;margin:0}header span,small{font-size:11px;color:var(--text-muted)}small{display:block}p{font-size:11px;color:var(--text-muted);line-height:1.8;overflow-wrap:anywhere}.selectors{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}.selectors>*{flex:1;min-width:180px}.table-scroll{overflow:auto;max-width:100%;border-block:1px solid var(--border)}table{border-collapse:collapse;min-width:100%;white-space:nowrap;font-size:11px}th,td{text-align:right;padding:10px 12px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}th{font-weight:500;color:var(--text-muted)}th:first-child,td:first-child{text-align:left}details{border-top:1px solid var(--border);padding:12px 0}summary{font-size:12px;cursor:pointer}details>p,details>:deep(.data-grid){margin-left:12px}.time-validation :deep(.chart-frame){margin-block:18px}.table-scroll:focus-visible{outline:2px solid var(--accent)}@media(max-width:480px){.selectors>*{min-width:100%}}
</style>
