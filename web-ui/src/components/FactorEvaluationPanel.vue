<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {submitFactorEvaluationTask,fetchTask,cancelTask,formatError} from '../api'
import {taskExecution} from '../task-execution'
import {taskStatusLabel,taskElapsed} from '../task-state'
import {taskProgressLabel} from '../task-progress'
import {useAuth} from '../auth'
import {useMarketPreferences} from '../market-preferences'
import {stockDisplayName} from '../stock-history'
import {factorValue,factorStatisticsLabel,sortedFactorRows,type FactorEvaluation} from '../factor-research'
import {browseFactors,factorLibraries,factorAvailabilityReason} from '../factor-catalog'
import MacSelect from './MacSelect.vue'
import StocksPicker from './StocksPicker.vue'
import AdjustPicker from './AdjustPicker.vue'
import ChartFrame from './ChartFrame.vue'
import DataProvenance from './DataProvenance.vue'
import FactorDiagnosticChart from './FactorDiagnosticChart.vue'
import FactorDefinitionDetails from './FactorDefinitionDetails.vue'
import FactorParameterEditor from './FactorParameterEditor.vue'
import FactorArchiveTools from './FactorArchiveTools.vue'
import FactorFavoriteButton from './FactorFavoriteButton.vue'
import {useFactorFavorites} from '../use-factor-favorites'
import FactorValidationSettings from './FactorValidationSettings.vue'
import FactorValidationReport from './FactorValidationReport.vue'
import FactorHorizonComparison from './FactorHorizonComparison.vue'
import FactorCompositionSettings from './FactorCompositionSettings.vue'
import FactorCompositionResult from './FactorCompositionResult.vue'
import FactorTrackingBridge from './FactorTrackingBridge.vue'
import {compositionConfig,compositionDefaults} from '../factor-composition'
import {selectedHorizons,horizonView} from '../factor-horizons'
import {validationConfig,validationDefaults} from '../factor-validation'
import {factorParameterError,factorWarmupWarnings,parameterizedFactorName,selectedFactorParameters,type FactorParameters} from '../factor-parameters'

const props=defineProps<{factors:Array<Record<string,unknown>>;names:Record<string,string>}>()
const symbols=ref(['SZ:000001','SH:600036','SH:601166','SH:601998','SH:601818','SH:600000','SH:600016','SH:600015'])
const selected=ref(['momentum_20d','volatility_20d'])
const factorParameters=ref<FactorParameters>({})
const parameterError=computed(()=>factorParameterError(selected.value,props.factors,factorParameters.value))
const library=ref('easy_tdx_builtin'),query=ref(''),factorLimit=ref(24)
const favorites=useFactorFavorites(),onlyFavorites=ref(false)
const favoriteKey=(f:Record<string,unknown>)=>String(f.canonical_name??f.name)
watch([library,query,onlyFavorites],()=>{factorLimit.value=24})
const horizons=ref<number[]>([5]),displayHorizon=ref(5)
const horizon=computed(()=>String(horizons.value[0]??5)),groups=ref('5'),count=ref('300'),preprocess=ref('raw')
const validation=ref(validationDefaults())
const composition=ref(compositionDefaults())
const warmupWarnings=computed(()=>factorWarmupWarnings(selected.value,props.factors,factorParameters.value,Number(count.value)))
const report=ref<FactorEvaluation|null>(null),focus=ref(''),order=ref('desc')
const {adjustMode}=useMarketPreferences(),{currentUser}=useAuth()
const task=taskExecution<Parameters<typeof submitFactorEvaluationTask>[0],FactorEvaluation>({owner:()=>currentUser.value?.id,submit:submitFactorEvaluationTask,poll:fetchTask,cancel:cancelTask,timeout:12*60*1000,interval:1500})
const {running:loading,error,taskId,state:taskState,cancelError,cancelling}=task
const statusText=computed(()=>taskState.value?`${taskStatusLabel(taskState.value)} · ${taskElapsed(taskState.value.elapsed??0)}`:loading.value?'正在获取完整股票池行情并提交任务…':'')
const unavailableReason=(factor:Record<string,unknown>)=>factorAvailabilityReason(factor,adjustMode.value,'DAY',true)
const availabilityWarnings=computed(()=>selected.value.flatMap(key=>{
  const factor=props.factors.find(f=>f.name===key),reason=factor?unavailableReason(factor):''
  return reason?[`${name(key)}：${reason}`]:[]
}))
let generation=0
const name=(key:string)=>{
  const definition=report.value?.factor_definitions?.[key]??props.factors.find(f=>f.name===key)
  return definition?parameterizedFactorName(definition,factorParameters.value[key]):props.names[key]??key
}
const eligible=computed(()=>props.factors.filter(f=>f.evaluation_available===true&&(!f.alias_of||selected.value.includes(String(f.name)))))
const matching=computed(()=>browseFactors(eligible.value,library.value,query.value,selected.value).filter(f=>!onlyFavorites.value||favorites.items.value.includes(favoriteKey(f))))
const detailReport=computed(()=>horizonView(report.value,displayHorizon.value))
const active=computed(()=>detailReport.value?.reports.find(r=>r.name===focus.value)??detailReport.value?.reports[0])
const ranking=computed(()=>sortedFactorRows(report.value?.latest??[],active.value?.name??'',order.value==='desc'?-1:1))
const inputKey=computed(()=>JSON.stringify([symbols.value,selected.value,factorParameters.value,horizon.value,horizons.value,groups.value,count.value,preprocess.value,validation.value,composition.value,adjustMode.value,currentUser.value?.id]))
watch(()=>currentUser.value?.id,()=>{factorParameters.value={};validation.value=validationDefaults();horizons.value=[5];composition.value=compositionDefaults()},{flush:'sync'})
function invalidate(){generation++;task.clear();report.value=null}
watch(inputKey,invalidate,{flush:'sync'});onBeforeUnmount(invalidate)
function toggle(key:string){selected.value=selected.value.includes(key)?selected.value.filter(x=>x!==key):selected.value.length<4?[...selected.value,key]:selected.value}
function toggleHorizon(value:number){horizons.value=horizons.value.includes(value)?horizons.value.filter(h=>h!==value):[...horizons.value,value].sort((a,b)=>a-b)}
async function run(){
  if(availabilityWarnings.value.length){error.value=availabilityWarnings.value.join('；');return}
  if(parameterError.value){error.value=parameterError.value;return}
  if(symbols.value.length<5||symbols.value.length>20||!selected.value.length){error.value='请选择 5—20 只标的和 1—4 个因子';return}
  invalidate();const stamp=generation
  try{
    const chosen=selectedHorizons(horizons.value)
    const split=validationConfig(validation.value,Math.max(...chosen),Number(count.value))
    const combined=compositionConfig(composition.value,selected.value)
    const completed=await task.run({stocks:symbols.value.map(s=>{const [market='',code='']=s.split(':');return {market,code}}),factors:[...selected.value],factor_parameters:selectedFactorParameters(selected.value,factorParameters.value),count:Number(count.value),horizon:chosen[0]!,horizons:chosen,groups:Number(groups.value),preprocess:preprocess.value,adjust:adjustMode.value,validation:split,composition:combined})
    if(stamp!==generation||!completed)return
    const result=task.result.value
    if(result?.version!=='factor-cross-section-v1'||!Array.isArray(result.reports))throw Error('因子检验返回格式不完整')
    report.value=result;focus.value=result.reports[0]?.name??'';displayHorizon.value=result.settings.horizon
  }catch(e){if(stamp===generation)error.value=formatError(e)}
}
</script>
<template>
  <div class="evaluation-workspace">
    <aside class="evaluation-config">
      <header><h3>样本与因子</h3><p>已收盘日线 · 5—20 只标的 · 最多 4 个因子</p></header>
      <StocksPicker v-model="symbols" category="DAY" />
      <MacSelect v-model="library" aria-label="检验因子库" :options="factorLibraries" />
      <input v-model="query" type="search" aria-label="查找检验因子" placeholder="库内搜索 · 名称或标识" />
      <label class="favorites-filter"><input v-model="onlyFavorites" type="checkbox">仅看收藏 · {{ favorites.items.value.length }} 项</label>
      <p v-if="favorites.message.value" role="alert">{{ favorites.message.value }}</p>
      <div class="selected-factors"><button v-for="key in selected" :key="key" :aria-label="`移除${name(key)}`" @click="toggle(key)">{{ name(key) }} ×</button></div>
      <FactorParameterEditor v-model="factorParameters" :names="selected" :definitions="props.factors" />
      <FactorCompositionSettings v-model="composition" :names="selected" :labels="Object.fromEntries(selected.map(n=>[n,name(n)]))" />
      <p v-if="parameterError" class="error-banner" role="alert">{{ parameterError }}</p>
      <p v-for="warning in warmupWarnings" :key="warning" role="status">{{ warning }}</p>
      <p v-for="warning in availabilityWarnings" :key="warning" role="status">{{ warning }}</p>
      <fieldset><legend>检验因子 <span>{{ selected.length }}/4</span></legend><div v-for="factor in matching.slice(0,factorLimit)" :key="String(factor.name)" class="factor-choice"><label><input type="checkbox" :checked="selected.includes(String(factor.name))" :disabled="!selected.includes(String(factor.name))&&(selected.length>=4||!!unavailableReason(factor))" @change="toggle(String(factor.name))"><span>{{ name(String(factor.name)) }}<small v-if="unavailableReason(factor)" class="availability-note">{{ unavailableReason(factor) }}</small></span></label><FactorFavoriteButton :name="name(String(factor.name))" :active="favorites.items.value.includes(favoriteKey(factor))" :busy="favorites.saving.value" @toggle="favorites.toggle(favoriteKey(factor))" /></div><p v-if="!matching.length">当前收藏、因子库或搜索没有匹配的可检验因子。</p></fieldset>
      <button v-if="matching.length>factorLimit" @click="factorLimit+=24">再展开 24 项（共 {{ matching.length }} 项）</button>
      <fieldset class="horizon-options"><legend>远期窗口 · 可多选</legend><label v-for="n in [1,5,10,20]" :key="n"><input type="checkbox" :checked="horizons.includes(n)" :aria-label="`${n} 个观测日远期窗口`" @change="toggleHorizon(n)">{{ n }} 个观测日</label></fieldset>
      <AdjustPicker compact />
      <FactorValidationSettings v-model="validation" />
      <details class="advanced"><summary>高级设置</summary><div class="parameter"><label>历史长度</label><MacSelect v-model="count" aria-label="检验历史长度" :options="[120,300,500,800].map(n=>({value:String(n),label:`${n} 根`}))" /></div><div class="parameter"><label>分位组数</label><MacSelect v-model="groups" aria-label="分位组数" :options="[{value:'3',label:'三组'},{value:'5',label:'五组'}]" /></div><div class="parameter"><label>截面预处理</label><MacSelect v-model="preprocess" aria-label="截面预处理" :options="[{value:'raw',label:'原始值'},{value:'mad_zscore',label:'中位去极值＋标准化'}]" /></div><p>只在同一天横截面处理，不填充缺失值。相同因子值不强制拆入不同组。</p></details>
      <button class="primary" :disabled="loading" @click="run">{{ loading?'正在获取行情并检验…':'开始因子检验' }}</button>
      <div v-if="loading||taskId" class="task-status">
        <p role="status" aria-live="polite">{{ statusText }}</p>
        <p v-if="taskState?.progress" class="work-progress">{{ taskProgressLabel(taskState.progress) }}<small>本阶段处理量，不代表整体完成比例；以任务最终状态为准。</small></p>
        <div class="task-actions"><button v-if="loading&&taskId" :disabled="cancelling||taskState?.status==='cancelling'" @click="task.cancel">{{ cancelling?'正在提交取消…':'取消后台任务' }}</button><button v-if="loading" @click="invalidate">停止等待</button><RouterLink v-if="taskId" to="/account">查看后台任务</RouterLink></div>
        <p>停止等待或修改输入不会取消后台计算。取得任务编号后可取消；未取得编号时，请到个人账户确认提交状态。</p>
        <p v-if="cancelError" role="alert" class="error-banner">取消未确认：{{ cancelError }}</p>
      </div>
      <p class="scope-note">默认样本仅为可编辑示例，不是推荐组合。估值因子与缠论因子暂不参与截面检验。</p>
    </aside>
    <section class="evaluation-results" :aria-busy="loading">
      <FactorArchiveTools mode="evaluation" :result="report" :busy="loading" />
      <p v-if="error" role="alert" class="error-banner">{{ error }}</p>
      <div v-if="!report" class="evaluation-empty"><h3>检验因子与后续收益的关系</h3><p>选择样本后，查看排序相关、分层收益与因子间的重复信息。</p><p>这是回顾性研究，不是策略回测；样本外边界以所选时间划分为准。</p><p v-if="loading" role="status">{{ statusText }} 行情不足会明确报错，不静默缩小样本。</p></div>
      <template v-else-if="detailReport">
        <FactorHorizonComparison v-if="report.horizon_comparison" v-model="displayHorizon" :value="report.horizon_comparison" :labels="Object.fromEntries(report.reports.map(r=>[r.name,name(r.name)]))" @select-factor="focus=$event" />
        <FactorValidationReport v-if="detailReport.validation" :key="displayHorizon" :value="detailReport.validation" :factor="active?.name" :labels="Object.fromEntries(report.reports.map(r=>[r.name,name(r.name)]))" />
        <FactorCompositionResult v-if="report.composition" :value="report.composition" :horizon="displayHorizon" :labels="Object.fromEntries(selected.map(n=>[n,name(n)]))" />
        <FactorTrackingBridge :result="report" />
        <header class="result-heading"><div><h3>截面检验结果</h3><p>{{ report.start }} — {{ report.end }} · {{ report.assets }} 只 · {{ report.date_count }} 个观测日</p></div></header>
        <p v-for="(message,key) in report.errors" :key="key" class="error-banner">{{ name(String(key)) }}：{{ message }}</p>
        <div class="table-scroll" tabindex="0" aria-label="因子检验汇总"><table><thead><tr><th>因子</th><th>覆盖率</th><th>有效截面</th><th>秩相关均值</th><th>信息比率</th><th>正相关占比</th><th>高组－低组</th></tr></thead><tbody><tr v-for="r in detailReport.reports" :key="r.name" :class="{selected:r.name===active?.name}"><th><button @click="focus=r.name">{{ name(r.name) }}</button></th><td>{{ factorValue(r.coverage,true) }}</td><td>{{ r.observations }}</td><td>{{ factorValue(r.rank_ic_mean) }}</td><td>{{ factorValue(r.rank_ic_ir) }}</td><td>{{ factorValue(r.positive_rate,true) }}</td><td>{{ factorValue(r.spread,true) }}</td></tr></tbody></table></div>
        <template v-if="active">
          <div class="detail-heading"><h3>{{ name(active.name) }}</h3><MacSelect v-model="focus" aria-label="查看检验因子" :options="report.reports.map(r=>({value:r.name,label:name(r.name)}))" /></div>
          <FactorDefinitionDetails v-if="report.factor_definitions?.[active.name]" :definition="report.factor_definitions[active.name]!" />
          <ChartFrame title="秩相关时间序列" description="每日秩相关与连续 20 个有效观测日均值；缺口保持为空"><FactorDiagnosticChart correlation :labels="active.daily.map(d=>d.date)" :series="[{name:'每日秩相关',values:active.daily.map(d=>d.rank_ic)},{name:'20 日均值',values:active.daily.map(d=>d.rolling_rank_ic)}]" /></ChartFrame>
          <ChartFrame title="分层平均远期收益" :description="`第 1 组为因子低值组 · ${active.layer_dates} 个完整分层截面 · 非策略净值`"><FactorDiagnosticChart bar percent :labels="active.layer_means.map((_,i)=>`第 ${i+1} 组`)" :series="[{name:'平均远期收益',values:active.layer_means}]" /></ChartFrame>
          <details class="detail-section" :open="active.observations===0"><summary>未参与统计的原因</summary><p v-if="active.observations===0">当前没有可定义的相关系数；空值不是零相关。</p><p v-if="!Object.keys(active.diagnostics).length">所选因子全部观测日均通过数据要求。</p><p v-for="(n,reason) in active.diagnostics" :key="reason">{{ reason }}：{{ n }} 个观测日</p><p>原因可只影响分层或相关；覆盖率不等同于有效检验比例。缺失不是 0。</p></details>
          <details class="detail-section"><summary>每日检验明细</summary><div class="table-scroll" tabindex="0"><table><thead><tr><th>日期</th><th>标的数</th><th>线性相关</th><th>秩相关</th><th v-for="(_,i) in active.layer_means" :key="i">第 {{ i+1 }} 组</th><th>说明</th></tr></thead><tbody><tr v-for="day in active.daily" :key="day.date"><td>{{ day.date }}</td><td>{{ day.n }}</td><td>{{ factorValue(day.ic) }}</td><td>{{ factorValue(day.rank_ic) }}</td><td v-for="(v,i) in day.layers" :key="i">{{ factorValue(v,true) }}</td><td>{{ day.reason??'有效' }}</td></tr></tbody></table></div></details>
          <details class="detail-section"><summary>最新因子排序 · {{ report.end }}</summary><p>显示该观测日的因子值，不使用其后收益排序；空值置于末尾。</p><MacSelect v-model="order" aria-label="因子排序方向" :options="[{value:'desc',label:'从高到低'},{value:'asc',label:'从低到高'}]" /><div class="table-scroll"><table><thead><tr><th>标的</th><th>{{ name(active.name) }}</th></tr></thead><tbody><tr v-for="row in ranking" :key="String(row.code)"><th>{{ stockDisplayName(String(row.code)) }}</th><td>{{ factorValue(row[active.name]) }}</td></tr></tbody></table></div></details>
        </template>
        <details class="detail-section"><summary>因子相关性 · 重复信息检查</summary><p>逐日横截面秩相关的平均值；不是个股时间序列相关。</p><div class="table-scroll" tabindex="0"><table><thead><tr><th>因子</th><th v-for="r in report.reports" :key="r.name">{{ name(r.name) }}</th></tr></thead><tbody><tr v-for="left in report.reports" :key="left.name"><th>{{ name(left.name) }}</th><td v-for="right in report.reports" :key="right.name">{{ factorValue(report.redundancy.find(r=>r.left===left.name&&r.right===right.name)?.correlation) }}</td></tr></tbody></table></div></details>
        <details class="detail-section" open><summary>计算口径与研究边界</summary><p>统计版本：<code>{{ factorStatisticsLabel(report) }}</code></p><p>覆盖率统计原始有效因子值，不代表相关系数有效。近常数收益仍可显示描述性分层均值，但不能据此判断因子排序能力。</p><ul><li v-for="note in report.limitations" :key="note">{{ note }}</li></ul><p>合并日期中的缺失行情：{{ report.missing_bars }} 条。数据指纹：<code>{{ report.input_fingerprint }}</code></p></details>
        <details class="detail-section"><summary>各标的数据来源</summary><div v-for="source in report.provenance" :key="source.code"><h4>{{ stockDisplayName(source.code) }}</h4><DataProvenance :metadata="source.metadata" :count="source.count" /></div></details>
      </template>
    </section>
  </div>
</template>
<style scoped>
.favorites-filter{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text-muted)}.factor-choice{display:flex;align-items:center;gap:5px;min-width:0}.factor-choice label{flex:1;min-width:0;overflow-wrap:anywhere}
.task-status{border-top:1px solid var(--border);padding-top:10px}.task-actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.task-actions button,.task-actions a{font-size:11px}.task-actions a{color:var(--accent)}
.work-progress{overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.work-progress small{display:block;font-size:10px}
.horizon-options{display:grid;grid-template-columns:1fr 1fr;gap:4px}.horizon-options legend{grid-column:1/-1}.horizon-options label{min-height:32px}
.availability-note{display:block;font-size:10px;color:var(--text-muted);line-height:1.6;margin-top:3px}
.selected-factors{display:flex;flex-wrap:wrap;gap:6px}.selected-factors button{font-size:11px;padding:5px 8px}.evaluation-config>input[type=search]{width:100%;min-width:0;font-size:12px}
.evaluation-workspace{padding:18px;border:1px solid var(--border);border-radius:12px;background:rgba(255,255,255,.014)}
.evaluation-config input[type=checkbox]{flex-shrink:0}
@media(max-width:600px){.evaluation-workspace{padding:12px}}
.evaluation-workspace{display:grid;grid-template-columns:260px minmax(0,1fr);gap:22px;min-width:0}.evaluation-config{border-right:1px solid var(--border);padding-right:20px;display:flex;flex-direction:column;gap:17px;min-width:0}.evaluation-config h3,.result-heading h3,.detail-heading h3{font-size:14px;font-weight:600}p{font-size:11px;color:var(--text-muted);line-height:1.8;margin:6px 0}fieldset{border:0;padding:0;margin:0;max-height:260px;overflow:auto}legend{font-size:12px;padding:0 0 9px;width:100%}legend span{float:right;color:var(--text-dim)}fieldset label{display:flex;align-items:center;gap:8px;padding:6px 0;font-size:12px}input[type=checkbox]{width:14px;height:14px;min-height:0;margin:0;accent-color:var(--accent)}.parameter{display:grid;grid-template-columns:80px minmax(0,1fr);align-items:center;gap:8px}.parameter label{font-size:11px;color:var(--text-muted)}summary{cursor:pointer;font-size:12px;line-height:1.6}.advanced .parameter{margin-top:12px}.scope-note{font-size:10px}.evaluation-results{min-width:0;display:flex;flex-direction:column;gap:16px}.evaluation-empty{padding:50px 24px;text-align:center;border-bottom:1px solid var(--border)}.evaluation-empty h3{font-size:16px;font-weight:500}.result-heading,.detail-heading{display:flex;align-items:center;justify-content:space-between;gap:14px}.result-heading button{flex-shrink:0}.detail-heading :deep(.mac-select){width:205px;max-width:60%}.table-scroll{overflow:auto;max-width:100%;max-height:420px;border-block:1px solid var(--border)}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:11px}th,td{padding:11px 12px;border-bottom:1px solid var(--border);text-align:right;font-variant-numeric:tabular-nums}th{font-weight:500;color:var(--text-muted)}th:first-child,td:first-child{text-align:left}thead th{background:var(--bg-panel);position:sticky;top:0}th button{background:none;border:0;padding:0;color:inherit;font:inherit;cursor:pointer}.selected{background:rgba(10,132,255,.08)}.selected th{color:var(--text)}.detail-section{border-top:1px solid var(--border);padding-top:14px}.detail-section>div,.detail-section>p,.detail-section>ul{margin:12px 0 0 12px}.detail-section li{font-size:11px;color:var(--text-muted);line-height:1.9;margin-bottom:5px}.detail-section code{overflow-wrap:anywhere;font-size:10px}.detail-section h4{font-size:12px;font-weight:500;padding-top:8px}.error-banner{padding:10px;font-size:12px}.chart-frame:deep(.chart-frame-content){display:block}.table-scroll:focus-visible{outline:2px solid var(--accent)}@media(max-width:1000px){.evaluation-workspace{grid-template-columns:1fr}.evaluation-config{border-right:0;padding-right:0;border-bottom:1px solid var(--border);padding-bottom:18px}fieldset{display:grid;grid-template-columns:1fr 1fr;max-height:210px}.result-heading{align-items:flex-start}}@media(max-width:420px){.result-heading{flex-direction:column}.detail-heading{flex-wrap:wrap}.detail-heading :deep(.mac-select){width:100%;max-width:100%}fieldset label{font-size:11px}}
</style>
