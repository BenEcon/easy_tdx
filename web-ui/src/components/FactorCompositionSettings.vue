<script setup lang="ts">
import {computed} from 'vue'
import MacSelect from './MacSelect.vue'
import {compositionConfig,type CompositionDraft} from '../factor-composition'
const props=defineProps<{names:string[];labels:Record<string,string>}>()
const model=defineModel<CompositionDraft>({required:true})
const current=(n:string)=>model.value.components[n]??{weight:1,direction:1}
function update(name:string,field:'weight'|'direction',value:number){model.value={...model.value,components:{...model.value.components,[name]:{...current(name),[field]:value}}}}
const checked=computed(()=>{try{return {value:compositionConfig(model.value,props.names),error:''}}catch(e){return {value:null,error:String(e).replace(/^Error: /,'')}}})
const total=computed(()=>checked.value.value?.components.reduce((s,c)=>s+c.weight,0)??0)
</script>
<template><details class="composition-settings"><summary>多因子组合 <span>{{ model.enabled?'已启用':'可选' }}</span></summary>
  <label class="enable"><input type="checkbox" :checked="model.enabled" @change="model={...model,enabled:($event.target as HTMLInputElement).checked}">同时检验固定权重组合</label>
  <template v-if="model.enabled">
    <p>同日排名后加权。正向保留高值，反向保留低值；不会按收益自动调整方向。</p>
    <div class="members"><div v-for="key in names" :key="key" class="member"><strong>{{ labels[key]??key }}</strong><div class="controls">
      <label>权重<input type="number" min="0.01" max="100" step="0.01" :aria-label="`${labels[key]??key}组合权重`" :value="current(key).weight" @input="update(key,'weight',Number(($event.target as HTMLInputElement).value))"></label>
      <MacSelect :model-value="String(current(key).direction)" :aria-label="`${labels[key]??key}组合方向`" :options="[{value:'1',label:'正向'},{value:'-1',label:'反向'}]" @update:model-value="update(key,'direction',Number($event))" />
      <small>{{ total?`${(current(key).weight/total*100).toFixed(2)}%`:'—' }}</small>
    </div></div></div>
    <p v-if="checked.error" role="alert" class="error">{{ checked.error }}</p><p>权重自动除以总和。缺失标的不补零、不重分配权重；完整标的不足 5 只时不评分。不是交易持仓比例。</p>
  </template>
</details></template>
<style scoped>
.composition-settings{border-block:1px solid var(--border);padding:13px 0;min-width:0}summary{font-size:12px;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:10px}summary span{color:var(--text-muted);font-size:10px}.enable{display:flex;align-items:center;gap:8px;margin:14px 0;font-size:12px}.enable input{width:14px;height:14px;min-height:0;accent-color:var(--accent)}p{font-size:11px;color:var(--text-muted);line-height:1.8}.members{margin-left:10px}.member{padding:12px 0;border-bottom:1px solid var(--border)}.member:last-child{border:0}.member strong{font-size:11px;font-weight:500;display:block;overflow-wrap:anywhere}.controls{display:grid;grid-template-columns:minmax(65px,1fr) 76px 50px;align-items:end;gap:8px;margin-top:7px}.controls label{font-size:10px;color:var(--text-muted)}.controls input{display:block;width:100%;height:32px;min-height:32px;margin-top:4px;font-size:12px;font-variant-numeric:tabular-nums}.controls small{text-align:right;font-size:10px;font-variant-numeric:tabular-nums;padding-bottom:9px;color:var(--text-muted)}.controls :deep(.mac-select-trigger){min-height:32px}.error{color:var(--danger)}
</style>
