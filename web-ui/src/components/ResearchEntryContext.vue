<script setup lang="ts">
import { periodLabel } from '../period-comparison'
import { trackingLabels } from '../tracking'
import type { ResearchNavigation } from '../research-navigation'
defineProps<{value:ResearchNavigation|null;error:string;backtest?:boolean}>()
</script>
<template>
  <aside class="entry-context" aria-label="研究入口参数">
    <p v-if="error" role="alert">入口参数无效：{{ error }}。请返回来源页面重新选择。</p>
    <template v-else-if="value">
      <strong>来自{{ value.source==='market'?'市场行情':'板块研究' }} · {{ trackingLabels[value.target.kind] }} · {{ value.target.market }}:{{ value.target.code }} {{ value.target.name }}</strong>
      <p>带入{{ periodLabel(value.category) }} · {{ {QFQ:'前复权',HFQ:'后复权',NONE:'不复权'}[value.adjust] }}。{{ backtest?'日期范围与策略采用本页设置。':'最近 '+value.count+' 根。' }}请检查当前设置后手动开始；这是重新取数分析，不是来源排行的历史快照。</p>
    </template>
  </aside>
</template>
<style scoped>
.entry-context{flex-shrink:0;padding:12px 14px;border-bottom:1px solid var(--border);line-height:1.7;overflow-wrap:anywhere}.entry-context strong{font-size:12px;font-weight:550;color:var(--text)}.entry-context p{font-size:11px;color:var(--text-muted);margin:3px 0 0}.entry-context [role=alert]{color:var(--danger)}
</style>
