<script setup lang="ts">
import MacSelect from './MacSelect.vue'
import NumberStepper from './NumberStepper.vue'
import type {ValidationDraft} from '../factor-validation'
const model=defineModel<ValidationDraft>({required:true})
function update(key:keyof ValidationDraft,value:string|number){model.value={...model.value,[key]:value}}
</script>
<template><details class="validation-settings" open>
  <summary>时间划分</summary>
  <MacSelect :model-value="model.mode" aria-label="时间检验方式" :options="[{value:'full',label:'全样本 · 回顾性'},{value:'holdout',label:'按日期 · 训练／验证／测试'},{value:'walk_forward',label:'滚动 · 向前检验'}]" @update:model-value="update('mode',$event)" />
  <template v-if="model.mode==='holdout'">
    <label>训练截止日<input type="date" aria-label="训练截止日" :value="model.trainEnd" @input="update('trainEnd',($event.target as HTMLInputElement).value)" /></label>
    <label>验证截止日<input type="date" aria-label="验证截止日" :value="model.validationEnd" @input="update('validationEnd',($event.target as HTMLInputElement).value)" /></label>
    <p>两次截止日均包含当日；其后为测试区间。按实际行情日期划分，不随机抽样。</p>
  </template>
  <template v-if="model.mode==='walk_forward'">
    <MacSelect :model-value="model.training" aria-label="滚动训练窗口" :options="[{value:'expanding',label:'训练窗口逐步扩展'},{value:'rolling',label:'训练窗口保持定长'}]" @update:model-value="update('training',$event)" />
    <label>训练根数<NumberStepper :model-value="model.trainBars" :min="20" :max="700" aria-label="训练根数" compact @update:model-value="update('trainBars',$event)" /></label>
    <label>验证根数<NumberStepper :model-value="model.validationBars" :min="10" :max="300" aria-label="验证根数" compact @update:model-value="update('validationBars',$event)" /></label>
    <label>测试根数<NumberStepper :model-value="model.testBars" :min="10" :max="300" aria-label="测试根数" compact @update:model-value="update('testBars',$event)" /></label>
    <p>每次向前移动一个测试窗口，测试日期不重复；末尾不足一窗仍展示并标注。</p>
  </template>
  <p v-if="model.mode!=='full'">固定本次因子参数，不自动训练或调参。跨区间的远期收益标签剔除；预热可使用此前行情。</p>
</details></template>
<style scoped>
.validation-settings{min-width:0;border-top:1px solid var(--border);padding-top:12px}.validation-settings summary{font-size:12px;cursor:pointer;margin-bottom:12px}.validation-settings>:not(summary){margin-top:10px}label{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;color:var(--text-muted);font-size:11px}input{min-width:0;max-width:100%;font-size:12px;color-scheme:dark}.validation-settings :deep(.number-stepper){width:94px}p{font-size:11px;color:var(--text-muted);line-height:1.8}label:has(input){display:grid;grid-template-columns:1fr}summary:focus-visible{outline:2px solid var(--accent)}
</style>
