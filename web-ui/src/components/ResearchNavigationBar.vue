<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import MacSelect from './MacSelect.vue'
import { useMarketPreferences } from '../market-preferences'
import { navigationPeriods, canOpenBacktest, researchNavigationQuery, type NavigationTarget } from '../research-navigation'
import { trackingLabels } from '../tracking'
import type { Category } from '../types'

const props=defineProps<{selection:NavigationTarget|null;source:'market'|'boards';busy?:boolean}>()
const category=ref<Category>('DAY')
const {adjustMode,adjustOptions}=useMarketPreferences()
const target=computed(()=>props.selection?.target)
const adjust=computed(()=>target.value?.kind==='stock'?adjustMode.value:'NONE')
const query=computed(()=>target.value?researchNavigationQuery({target:target.value,category:category.value,adjust:adjust.value,count:600,source:props.source}):null)
</script>
<template>
  <section class="navigation-bar" aria-label="继续研究选中标的">
    <div class="navigation-identity"><strong>{{ target ? `${target.code}-${target.name||'名称待补充'}` : '选择表格中的标的' }}</strong><small v-if="target">{{ trackingLabels[target.kind] }} · {{ target.market }} · 带入参数，不自动计算</small><small v-else>{{ selection?.error || '点击一行或用键盘选择后，可打开对应分析页面。' }}</small></div>
    <template v-if="target">
      <div class="navigation-setting"><span>分析周期</span><MacSelect v-model="category" :options="navigationPeriods" aria-label="继续研究周期" /></div>
      <div v-if="target.kind==='stock'" class="navigation-setting"><span>复权</span><MacSelect v-model="adjustMode" :options="adjustOptions" aria-label="继续研究复权" /></div><small v-else>不复权</small>
      <div class="navigation-actions" v-if="query&&!busy"><RouterLink :to="{path:'/chanlun',query}">缠论结构</RouterLink><RouterLink v-if="canOpenBacktest(target)" :to="{path:'/',query}">个股分析</RouterLink></div>
      <small v-else>正在更新来源数据…</small>
    </template>
  </section>
</template>
<style scoped>
.navigation-bar{display:flex;align-items:center;flex-wrap:wrap;gap:12px 18px;padding:12px 3px;border-top:1px solid var(--border);min-width:0;flex-shrink:0}.navigation-identity{min-width:0;flex:1 1 200px}.navigation-identity strong{font-size:12px;font-weight:550;color:var(--text);overflow-wrap:anywhere}.navigation-identity small{display:block;margin-top:4px}small,.navigation-setting>span{font-size:10px;line-height:1.6;color:var(--text-muted)}.navigation-setting{display:flex;align-items:center;gap:8px;min-width:0}.navigation-setting>span{white-space:nowrap}.navigation-setting :deep(.mac-select){width:120px}.navigation-actions{display:flex;flex-wrap:wrap;gap:8px}.navigation-actions a{display:inline-flex;align-items:center;min-height:34px;padding:5px 10px;border:1px solid var(--border);border-radius:7px;background:var(--bg-elevated);color:var(--text-muted);font-size:11px;text-decoration:none;transition:border-color .15s,color .15s}.navigation-actions a:hover{border-color:var(--accent);color:var(--accent)}a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:600px){.navigation-bar{gap:10px}.navigation-identity{flex-basis:100%}.navigation-actions a{min-height:40px}.navigation-setting :deep(.mac-select){width:115px}}@media(prefers-reduced-motion:reduce){a{transition:none}}
</style>
