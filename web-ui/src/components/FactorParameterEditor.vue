<script setup lang="ts">
import {computed} from 'vue'
import NumberStepper from './NumberStepper.vue'
import {editableFactorParameters,resetFactorParameter,type FactorParameters,type FactorDefinition} from '../factor-parameters'
const model=defineModel<FactorParameters>({required:true})
const props=defineProps<{names:string[];definitions:FactorDefinition[]}>()
const rows=computed(()=>props.names.flatMap(name=>{
  const definition=props.definitions.find(d=>d.name===name)
  return definition?editableFactorParameters(definition).map(([key,spec])=>({name,key,spec,definition})):[]
}))
function update(name:string,key:string,value:number){model.value={...model.value,[name]:{...model.value[name],[key]:value}}}
function reset(name:string,key:string){model.value=resetFactorParameter(model.value,name,key)}
</script>
<template>
  <details v-if="rows.length" class="factor-parameters" open>
    <summary>因子参数 <span>{{ rows.length }} 项可编辑</span></summary>
    <p>窗口单位为当前 K 线根数；修改后须重新计算。标识保留原值，结果记录实际公式与窗口。</p>
    <div v-for="row in rows" :key="`${row.name}:${row.key}`" class="parameter-row">
      <label><strong>{{ row.definition.parameterized_title??row.definition.display_name }}</strong><small>{{ row.name }} · {{ row.spec.label??'窗口' }} · 默认 {{ row.spec.default }} {{ row.spec.unit==='multiple'?'倍':'根' }}</small></label>
      <div class="parameter-actions"><NumberStepper :model-value="model[row.name]?.[row.key]??row.spec.default" :min="row.spec.min" :max="row.spec.max" :step="row.spec.step??1" :aria-label="`${row.name} ${row.spec.label??'窗口根数'}`" compact @update:model-value="update(row.name,row.key,$event)"/><button type="button" :disabled="model[row.name]?.[row.key]===undefined" :aria-label="`恢复${row.name}${row.spec.label??'窗口'}默认参数`" @click="reset(row.name,row.key)">重置</button></div>
    </div>
  </details>
</template>
<style scoped>
.factor-parameters{container-type:inline-size}@container(max-width:300px){.parameter-row>label{flex-basis:100%}.parameter-actions{margin-left:auto}}
.factor-parameters{min-width:0;border-block:1px solid var(--border);padding:12px 0;margin:10px 0;font-size:12px}.factor-parameters summary{cursor:pointer;font-weight:550}.factor-parameters summary span{font-weight:400;color:var(--text-dim);margin-left:8px;font-size:11px}.factor-parameters p{font-size:11px;color:var(--text-muted);line-height:1.8;margin:10px 0}.parameter-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:9px 0}.parameter-row+.parameter-row{border-top:1px solid var(--border)}label{min-width:0}strong{font-weight:500}small{display:block;font-size:10px;color:var(--text-dim);margin-top:4px;overflow-wrap:anywhere}.parameter-actions{display:flex;gap:8px;align-items:center;flex-shrink:0}.parameter-actions :deep(.number-stepper){width:94px}.parameter-actions button{font-size:11px;padding:5px 8px;min-height:30px;background:transparent;border:0;color:var(--text-muted)}button:disabled{opacity:.4}summary:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:600px){.parameter-row{flex-wrap:wrap}.parameter-actions{margin-left:auto}}@container(max-width:300px){.parameter-row{flex-wrap:wrap}}
</style>
