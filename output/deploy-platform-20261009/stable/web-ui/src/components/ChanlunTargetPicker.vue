<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { fetchBoardList, formatError } from '../api'
import { indexTargets, type ResearchTarget, type TargetKind, type BoardKind } from '../chanlun-target'
import MacSelect from './MacSelect.vue'

const model = defineModel<ResearchTarget>({ required: true })
const kind = computed({ get: () => model.value.kind, set: (kind: TargetKind) => {
  model.value = kind === 'index' ? { kind, market: 'SH', code: '000001', name: '上证指数' }
    : { kind, market: '', code: '', boardType: 'HY' }
} })
const kindOptions = [{ value: 'stock' as const, label: '个股' }, { value: 'index' as const, label: '指数' }, { value: 'board' as const, label: '板块' }]
const boardTypes: Array<{value: BoardKind; label: string}> = [
  {value:'HY',label:'一级行业'}, {value:'HY2',label:'二级行业'}, {value:'GN',label:'概念'},
  {value:'FG',label:'风格'}, {value:'DQ',label:'地区'},
]
const boardType = computed({ get: () => model.value.boardType ?? 'HY', set: (boardType: BoardKind) => {
  model.value = { kind: 'board', code: '', market: '', boardType }
} })
const indexKey = computed({ get: () => `${model.value.market}:${model.value.code}`, set: (value: string) => {
  const [market, code] = value.split(':')
  model.value = {kind:'index',market:market!,code:code!,name:indexTargets.find(i=>i.value===value)?.label.split('-').slice(1).join('-')}
} })
const boardCode = computed({ get: () => model.value.code, set: (code: string) => {
  const row = catalog.value.find(row => row.code === code)
  if (row) model.value = {kind:'board',code,market:row.market,name:row.name,boardType:boardType.value}
} })
const query = ref('')
const catalog = ref<Array<{code:string; market:string; name:string}>>([])
const loading = ref(false)
const error = ref('')
const options = computed(() => {
  const search = query.value.trim().toLowerCase()
  return catalog.value.filter(row => row.code === model.value.code || `${row.code} ${row.name}`.toLowerCase().includes(search))
    .map(row => ({value:row.code,label:`${row.code}-${row.name}`}))
})
let generation = 0
async function loadBoards() {
  const version = ++generation
  const selectedType = boardType.value
  catalog.value = []; error.value = ''; loading.value = true
  try {
    const response = await fetchBoardList({boardType:selectedType,count:5000})
    if (version !== generation) return
    catalog.value = response.data.filter(row => /^\d{6}$/.test(String(row.code)) && row.market != null)
      .map(row => ({code:String(row.code),name:String(row.name ?? row.code),market:String(row.market)}))
      .sort((a,b)=>a.code.localeCompare(b.code))
    if (!catalog.value.length) error.value = '此分类暂无板块，请切换分类或重试'
  } catch (e) { if (version === generation) error.value = formatError(e) }
  finally { if (version === generation) loading.value = false }
}
watch([kind,boardType], () => {
  generation++; query.value = ''; catalog.value = []; error.value = ''; loading.value = false
  if (kind.value === 'board') void loadBoards()
})
onBeforeUnmount(() => { generation++ })
</script>

<template>
  <div class="target-picker">
    <label>标的类型</label>
    <MacSelect v-model="kind" :options="kindOptions" aria-label="缠论标的类型" />
    <template v-if="kind === 'index'">
      <label>指数</label>
      <MacSelect v-model="indexKey" :options="indexTargets" aria-label="选择指数" />
      <small>沪深市场分别识别 · 不复权</small>
    </template>
    <template v-if="kind === 'board'">
      <label>板块分类</label>
      <MacSelect v-model="boardType" :options="boardTypes" aria-label="板块分类" />
      <label for="chanlun-board-search">查找板块</label>
      <input id="chanlun-board-search" v-model="query" placeholder="输入名称或代码筛选" autocomplete="off">
      <MacSelect v-model="boardCode" :options="options" :disabled="loading" :placeholder="loading ? '加载板块目录…' : '请选择板块'" aria-label="选择板块" />
      <small v-if="!loading && !error">{{ options.length }} 个匹配板块 · 不复权</small>
      <small v-if="error" role="alert">{{ error }}</small>
      <button v-if="error" type="button" @click="loadBoards">重新加载目录</button>
    </template>
  </div>
</template>

<style scoped>
.target-picker{display:grid;gap:9px;margin-bottom:16px;min-width:0}.target-picker>label{font-size:11px;color:var(--text-muted);margin-top:4px}.target-picker small{font-size:10px;line-height:1.5;color:var(--text-muted)}.target-picker input{width:100%;min-width:0}.target-picker button{font-size:11px;padding:6px 10px;justify-self:start}
</style>
