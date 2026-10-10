<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { eventChangeLabels, eventCollectionLabels, eventFacetLabels, type ArchiveEventComparison, type EventChange, type EventCollection, type EventReference } from '../archive-event-comparison'
import MacSelect from './MacSelect.vue'

const props = defineProps<{ report: ArchiveEventComparison }>()
const filter = ref<EventChange | 'differences' | 'all'>('differences'), collection = ref<EventCollection | 'all'>('all'), page = ref(0)
const opened = ref(new Set<string>())
const collectionOptions: {value: EventCollection | 'all'; label: string}[] = [{value:'all',label:'全部类型'},...Object.entries(eventCollectionLabels).map(([value,label])=>({value:value as EventCollection,label}))]
const filterOptions: {value: EventChange | 'differences' | 'all'; label: string}[] = [{value:'differences',label:'只看差异与待核验'},{value:'all',label:'全部记录'},...Object.entries(eventChangeLabels).map(([value,label])=>({value:value as EventChange,label}))]
const rows = computed(() => props.report.rows.filter(row => (collection.value === 'all' || row.collection === collection.value)
  && (filter.value === 'all' || (filter.value === 'differences' ? row.change !== 'same' : row.change === filter.value))))
const visible = computed(() => rows.value.slice(page.value * 30, (page.value + 1) * 30))
watch([filter, collection, () => props.report], () => { page.value = 0; opened.value = new Set() })
watch(page, () => { opened.value = new Set() })
function toggle(key: string, event: Event) {
  const next = new Set(opened.value)
  if ((event.target as HTMLDetailsElement).open) next.add(key); else next.delete(key)
  opened.value = next
}
function state(refs: EventReference[]) {
  if (!refs.length) return '无对应记录'
  if (refs.length > 1) return `${refs.length} 条同身份记录`
  const value = refs[0]!.value
  if (!value || typeof value !== 'object') return '格式不明'
  if ('status' in value) return ({ candidate: '候选', confirmed: '已确认', superseded: '已替代／失效', blocked: '未通过' } as Record<string,string>)[String(value.status)] ?? String(value.status)
  return 'confirmed_date' in value && value.confirmed_date ? '已记录确认日期' : '状态未记录'
}
const valueText = (value: unknown, present: boolean) => present ? JSON.stringify(value) : '〈字段缺失〉'
</script>
<template>
  <section class="event-comparison" aria-label="按事件对照">
    <header><h4>按事件对照</h4><span>日期依据配对 · 不按列表位置</span></header>
    <p v-for="warning in report.warnings" :key="warning" class="scope-note">{{ warning }}</p>
    <template v-if="report.applicable">
      <div class="event-counts" aria-label="事件变化统计">
        <button v-for="(label, key) in eventChangeLabels" :key="key" :aria-pressed="filter===key" @click="filter=key">{{ label }} <strong>{{ report.counts[key] }}</strong></button>
      </div>
      <div class="event-controls">
        <div class="event-control"><span class="filter-label">范围</span><MacSelect v-model="collection" :options="collectionOptions" aria-label="事件对照范围" /></div>
        <div class="event-control"><span class="filter-label">显示</span><MacSelect v-model="filter" :options="filterOptions" aria-label="事件对照显示" /></div>
        <span>{{ rows.length }} 组 · 每页 30 组</span>
      </div>
      <p v-if="!rows.length" role="status">当前筛选下无记录；不代表其他结构或原始字段完全一致。</p>
      <div class="event-rows">
        <details v-for="row in visible" :key="row.key" :open="opened.has(row.key)" @toggle="toggle(row.key,$event)">
          <summary>
            <span class="event-change">{{ eventChangeLabels[row.change] }}</span>
            <span class="event-identity"><strong>{{ row.label }}</strong><small>{{ eventCollectionLabels[row.collection] }} · {{ row.date || '日期依据缺失' }}</small></span>
            <span class="event-state"><span>{{ state(row.before) }}</span><span aria-label="变为"> → </span><span>{{ state(row.after) }}</span></span>
          </summary>
          <div v-if="opened.has(row.key)" class="event-evidence">
            <p v-if="row.reason">{{ row.reason }}</p>
            <p v-if="row.facets.length">变化范围：{{ row.facets.map(facet=>eventFacetLabels[facet]).join('、') }}。下方路径基于规范化的证据集合；原始位置与顺序见原记录。</p>
            <div v-if="row.differences.length" class="event-table" role="region" aria-label="事件字段变化" tabindex="0">
              <table><thead><tr><th>字段</th><th>原档</th><th>本次</th></tr></thead><tbody><tr v-for="diff in row.differences" :key="diff.path"><th scope="row">{{ diff.path }}</th><td><pre>{{ valueText(diff.before,diff.beforePresent) }}</pre></td><td><pre>{{ valueText(diff.after,diff.afterPresent) }}</pre></td></tr></tbody></table>
            </div>
            <details><summary>查看原始记录与位置（完整精度）</summary><pre>{{ JSON.stringify({before:row.before,after:row.after},null,2) }}</pre></details>
          </div>
        </details>
      </div>
      <nav v-if="rows.length>30" class="event-paging" aria-label="事件对照分页"><button :disabled="page===0" @click="page--">上一页</button><span>{{ page+1 }} / {{ Math.ceil(rows.length/30) }}</span><button :disabled="(page+1)*30>=rows.length" @click="page++">下一页</button></nav>
      <details class="coverage"><summary>配对覆盖与口径</summary><p v-for="item in report.coverage" :key="item.collection">{{ eventCollectionLabels[item.collection] }}：原档 {{ item.before ?? '未保存' }} 条，本次 {{ item.after ?? '未保存' }} 条。{{ item.comparable?'列表可比较；重复或缺失身份单独核验。':'未推断增删。' }}</p><p>同身份重复项合为一组，保留组内所有原记录。仅忽略核验条件、对照模式与相关事件等证据集合的排列；价格序列与线段顺序不忽略。所有原始字段变化仍在下方保留。</p></details>
    </template>
  </section>
</template>
<style scoped>
.event-comparison{min-width:0;margin:16px 0 24px;border-block:1px solid var(--border);padding:14px 0}
header{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px}h4{margin:0;font-size:13px;font-weight:600;color:var(--text-primary)}header>span,small,.event-controls>span{color:var(--text-muted);font-size:10px}
p{font-size:11px;line-height:1.8;color:var(--text-muted);overflow-wrap:anywhere}.scope-note{margin:6px 0}.event-counts{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}.event-counts strong{margin-left:8px;font-variant-numeric:tabular-nums;font-weight:600}
button,select{min-height:32px;border:1px solid var(--border);border-radius:6px;padding:5px 9px;background:var(--bg-elevated);color:var(--text-muted);font:inherit;font-size:11px}button{cursor:pointer;transition:color .15s,border-color .15s}button[aria-pressed=true],button:hover:not(:disabled){color:var(--accent);border-color:var(--accent)}button:disabled{opacity:.45;cursor:default}
.event-controls{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin:12px 0}.event-control{display:flex;gap:8px;align-items:center;font-size:11px;color:var(--text-muted);width:208px;max-width:100%;min-width:0}.filter-label{white-space:nowrap;flex:none}.event-control :deep(.mac-select){flex:1;min-width:0}.event-control :deep(.mac-select-trigger){min-height:36px}.event-controls>span{margin-left:auto}
.event-rows>details{border-top:1px solid var(--border)}summary{cursor:pointer;font-size:11px;padding:11px 0;color:var(--text-muted)}.event-rows>details>summary{display:grid;grid-template-columns:105px minmax(0,1fr) minmax(100px,auto);align-items:center;gap:12px;list-style:none}.event-rows>details>summary::-webkit-details-marker{display:none}.event-change::before{content:'›';display:inline-block;margin-right:8px;width:8px;transition:transform .15s}details[open]>summary .event-change::before{transform:rotate(90deg)}.event-identity strong{display:block;font-size:12px;font-weight:500;color:var(--text-primary)}small{display:block;margin-top:4px}.event-state{text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.event-evidence{padding:0 0 12px 16px;border-left:1px solid var(--border);margin:0 0 12px 3px;min-width:0}
.event-table{overflow:auto;max-height:380px;max-width:100%}table{width:100%;min-width:560px;table-layout:fixed;border-collapse:collapse;font-size:11px}td,th{padding:8px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border);overflow-wrap:anywhere}th{font-weight:500;color:var(--text-muted)}thead{position:sticky;top:0;background:var(--bg-panel,#1c1e23)}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:280px;overflow:auto;font-size:11px;line-height:1.7;margin:0}td pre{max-height:160px}.event-paging{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin-top:12px;font-size:11px;color:var(--text-muted)}.coverage{margin-top:8px}.coverage p{margin:4px 0}button:focus-visible,select:focus-visible,summary:focus-visible,.event-table:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:600px){.event-rows>details>summary{grid-template-columns:90px minmax(0,1fr);gap:8px}.event-state{grid-column:2;text-align:left}.event-controls>span{margin-left:0}.event-evidence{padding-left:10px}button,select{min-height:36px}.event-counts{gap:6px}}
@media(prefers-reduced-motion:reduce){button,.event-change::before{transition:none}}
</style>
