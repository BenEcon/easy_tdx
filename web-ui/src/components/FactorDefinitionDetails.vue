<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ definition: Record<string, unknown> }>()
const fieldNames:Record<string,string>={open:'开盘价',high:'最高价',low:'最低价',close:'收盘价',vol:'原生成交量',volume:'已核验成交量（股）',vwap:'同复权成交均价',amount:'成交额',financials_point_in_time:'历史时点财务',available_at:'公告可得时间',explicit_universe:'明确的股票池',benchmark_open:'基准指数开盘价',benchmark_close:'基准指数收盘价',risk_mkt:'市场超额收益（MKT）',risk_smb:'规模收益差（SMB）',risk_hml:'价值收益差（HML）'}
const periodNames:Record<string,string>={DAY:'日线',WEEK:'周线',MONTH:'月线',MIN_1:'1 分钟',MIN_5:'5 分钟',MIN_15:'15 分钟',MIN_30:'30 分钟',MIN_60:'60 分钟'}
const parameters = computed(() => Object.entries((props.definition.parameters ?? {}) as Record<string, {default: unknown; value?:unknown; editable: boolean; label?:string}>))
const fields = computed(() => Array.isArray(props.definition.data_requirements) ? props.definition.data_requirements.map(key=>`${fieldNames[String(key)]??key}（${key}）`).join('、') : '尚未登记')
const periods = computed(() => Array.isArray(props.definition.supported_categories) ? props.definition.supported_categories.map(key=>periodNames[String(key)]??key).join('、') : '尚未登记')
const adjustments=computed(()=>Array.isArray(props.definition.supported_adjustments)?props.definition.supported_adjustments.map(key=>({NONE:'不复权',QFQ:'前复权',HFQ:'后复权'}[String(key)]??key)).join('、'):null)
const limits = computed(() => Array.isArray(props.definition.limitations) ? props.definition.limitations : [])
const parameterNames:Record<string,string> = {window:'窗口',short:'短窗口',long:'长窗口',signal:'信号平滑',scale_window:'归一窗口',std_multiplier:'标准差倍数'}
</script>

<template>
  <details class="definition-details">
    <summary>公式、数据要求与版本</summary>
    <dl>
      <dt>公式</dt><dd><code>{{ definition.formula ?? '尚未登记' }}</code></dd>
      <dt>输入字段</dt><dd>{{ fields }}</dd>
      <dt>计算范围</dt><dd>{{ definition.scope === 'cross_section_panel' ? '股票池整池计算 · 同一时点对齐' : '单标的时间序列' }}</dd>
      <dt>最少输入</dt><dd>{{ definition.warmup_bars == null ? '无固定根数 / 尚未实现' : `${definition.warmup_bars} 根 K 线` }}<small>{{ definition.warmup_note }}</small></dd>
      <dt>参数</dt><dd><template v-if="parameters.length"><span v-for="[key,param] in parameters" :key="key" class="parameter">{{ param.label ?? parameterNames[key] ?? key }} {{ param.value ?? param.default }}{{ param.editable ? `（默认 ${param.default}）` : '（固定）' }}</span></template><template v-else>无可编辑参数</template></dd>
      <dt>支持周期</dt><dd>{{ periods }}</dd>
      <dt v-if="adjustments">支持复权</dt><dd v-if="adjustments">{{ adjustments }}<small>{{ definition.adjustment_unavailable_reason }}</small></dd>
      <dt>计算状态</dt><dd>{{ definition.available ? '可计算（仍需本次数据通过校验）' : definition.unavailable_reason }}<small v-if="definition.evaluation_unavailable_reason">截面检验：{{ definition.evaluation_unavailable_reason }}</small></dd>
      <dt>版本 / 来源</dt><dd>{{ definition.implementation_version }}<small>{{ definition.source }}</small></dd>
      <dt>定义指纹</dt><dd><code>{{ definition.formula_sha256 }}</code></dd>
      <dt v-if="definition.alias_of">同义定义</dt><dd v-if="definition.alias_of">{{ definition.name }} → {{ definition.alias_of }}；保留各自实现版本记录，不重复计数。</dd>
    </dl>
    <ul><li v-for="(limit,index) in limits" :key="index">{{ limit }}</li></ul>
  </details>
</template>

<style scoped>
.definition-details{grid-column:1/-1;min-width:0;font-size:11px;line-height:1.7;border-top:1px solid var(--border);padding-top:8px}.definition-details summary{cursor:pointer;color:var(--text-muted);padding:3px 0}.definition-details summary:hover{color:var(--text)}dl{display:grid;grid-template-columns:90px minmax(0,1fr);gap:7px 14px;margin:12px 0}dt{color:var(--text-dim)}dd{margin:0;color:var(--text-muted);overflow-wrap:anywhere}small{display:block;color:var(--text-dim);font-size:10px}.parameter{display:inline-block;margin-right:12px}code{font:10px var(--font-mono);white-space:normal;overflow-wrap:anywhere}ul{margin:10px 0;padding-left:18px;color:var(--text-dim)}@media(max-width:480px){dl{grid-template-columns:1fr;gap:3px}dd{padding-bottom:7px}}
</style>
