<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { fetchBoardMembers, fetchStockNames, formatError } from '../api'
import { refreshCurrentUser, updatePreferences, useAuth } from '../auth'
import { canUseTracking } from '../feature-access'
import { detectMarket } from '../market'
import type { ResearchTarget } from '../chanlun-target'
import { studyLabel, type StudyPeriod } from '../research-study'
import { periodOverviewCells } from '../period-overview'
import { emptyTrackingBook, readTrackingBook, trackingChartQuery, trackingKey, trackingLabels, trackingTitle, validateTrackingTarget, type BreadthFilter, type TrackingAnalysis, type TrackingBook, type TrackingKind, type TrackingTarget } from '../tracking'
import TrackingBreadth from '../components/TrackingBreadth.vue'
import {matchesBreadthFilters,matchesTrackingStatus} from '../tracking-filters'
import {trackingSession,trackingAutoSave} from '../tracking-background'
import CloudResearchArchives from '../components/CloudResearchArchives.vue'
import {analyzeTrackingTarget} from '../tracking-analysis'
import MacSelect from '../components/MacSelect.vue'
import ChanlunTargetPicker from '../components/ChanlunTargetPicker.vue'
import MultiPeriodOverviewTable from '../components/MultiPeriodOverviewTable.vue'

const { currentUser } = useAuth()
const router = useRouter()
const book = ref<TrackingBook>(emptyTrackingBook())
const {selectedId,periods,rows,issues,loading,phase,cutoff,completed,successful,failed,snapshot,error:analysisError} = trackingSession
const {pending:unsaved,busy:archiveSaving,error:archiveError,saved:archiveSaved}=trackingAutoSave
function downloadPending(){
  const payload=unsaved.value?.payload??trackingSession.archive.value
  if(!payload)return
  const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}))
  const a=document.createElement('a');a.href=url;a.download=`追踪分析-${payload.group.name}-${payload.cutoff.replace(/[: ]/g,'-')}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
const group = computed(() => snapshot.value?.group.id===selectedId.value ? snapshot.value.group : book.value.groups.find(item => item.id === selectedId.value))
const error = ref(''), notice = ref(''), corrupt = ref(false), saving = ref(false)
const groupName = ref(''), rename = ref(''), deleteGroup = ref(false)
const kind = ref<TrackingKind>('stock'), code = ref(''), name = ref('')
const picker = ref<ResearchTarget>({ kind:'index', market:'SH', code:'000001', name:'上证指数' })
const market = ref('SZ')
const kinds = Object.entries(trackingLabels).map(([value,label]) => ({value:value as TrackingKind,label}))
const marketOptions = [{value:'SZ',label:'深圳'},{value:'SH',label:'上海'},{value:'BJ',label:'北京'}]
watch(code, value => { market.value = detectMarket(value) })
watch(kind, value => {
  error.value = ''; code.value = ''; name.value = ''
  if (value === 'board') picker.value = {kind:'board',code:'',market:'',boardType:'HY'}
  if (value === 'index') picker.value = {kind:'index',code:'000001',market:'SH',name:'上证指数'}
})
const periodOptions = ['WEEK','DAY','MIN_60','MIN_30','MIN_15','MIN_5'] as const
const query = ref(''), filter = ref<string[]>([]), inspected = ref('')
const filterOptions = [{value:'done',label:'分析成功'},{value:'error',label:'分析失败'},{value:'cancelled',label:'已停止'},{value:'pending',label:'待分析'},{value:'running',label:'分析中'}]
const breadthFilter=ref<BreadthFilter[]>([])
function selectBreadth(value:BreadthFilter[]){breadthFilter.value=value;inspected.value='';page.value=1}
const visibleRows = computed(() => rows.value.filter(row => matchesBreadthFilters(row,breadthFilter.value) && matchesTrackingStatus(row,filter.value) && `${trackingTitle(row.target)} ${row.sources.join(' ')}`.includes(query.value.trim())))
const page = ref(1)
const resultScroll=ref<HTMLElement|null>(null)
watch([query,filter,breadthFilter,page],()=>{if(resultScroll.value)resultScroll.value.scrollTop=0},{deep:true,flush:'post'})
const pageCount = computed(() => Math.max(1,Math.ceil(visibleRows.value.length / 50)))
const pageRows = computed(() => visibleRows.value.slice((page.value-1)*50,page.value*50))
watch([query,filter],()=>{page.value=1;inspected.value=''}, {deep:true})
const statusLabel = { pending:'等待分析', running:'分析中', done:'完成', error:'失败', cancelled:'已停止' }
function stop() { trackingSession.stop() }
function clearResults() { trackingSession.clearResults(); inspected.value = ''; page.value = 1; breadthFilter.value=[] }
function hydrate() {
  try { book.value = readTrackingBook(currentUser.value?.preferences.tracking_groups); corrupt.value = false; error.value = '' }
  catch (e) { book.value = emptyTrackingBook(); corrupt.value = true; error.value = formatError(e) }
  if (!book.value.groups.some(item => item.id === selectedId.value) && !snapshot.value) selectedId.value = book.value.groups[0]?.id ?? ''
  rename.value = group.value?.name ?? ''
}
watch(() => currentUser.value?.id, () => { hydrate(); notice.value = ''; deleteGroup.value = false }, {immediate:true})
watch(selectedId, () => { clearResults(); rename.value = group.value?.name ?? ''; deleteGroup.value = false }, {flush:'sync'})
watch(periods, clearResults, {deep:true,flush:'sync'})
watch(()=>canUseTracking(currentUser.value),allowed=>{if(!allowed){clearResults();void router.replace({path:'/account',query:{notice:'tracking-access'}})}},{immediate:true})

async function persist(next: TrackingBook) {
  if (saving.value || loading.value || corrupt.value) return false
  const owner = currentUser.value?.id, revision = book.value.revision
  if (!owner) return false
  saving.value = true; error.value = ''; notice.value = ''
  try {
    next.revision = crypto.randomUUID(); readTrackingBook(next)
    // Detect already-committed edits from another tab/device before merging account preferences.
    await refreshCurrentUser()
    if (currentUser.value?.id !== owner) throw new Error('账户已切换，未保存到其他账户')
    if (readTrackingBook(currentUser.value.preferences.tracking_groups).revision !== revision) {
      hydrate(); throw new Error('分组已在其他页面更新，已载入最新版本，请重新操作')
    }
    if (new TextEncoder().encode(JSON.stringify({...currentUser.value.preferences, tracking_groups:next})).length > 60000) throw new Error('账户偏好存储接近上限，请减少直接追踪标的；板块成员无需逐只保存')
    await updatePreferences({tracking_groups:next})
    if (currentUser.value?.id !== owner) return false
    book.value = next; clearResults(); notice.value = '已保存到当前账户'
    return true
  } catch (e) { if (currentUser.value?.id === owner) error.value = formatError(e); return false }
  finally { saving.value = false }
}
function draft() { return JSON.parse(JSON.stringify(book.value)) as TrackingBook }
async function createGroup() {
  const title = groupName.value.trim()
  if (!title) return
  if (book.value.groups.some(item => item.name === title)) { error.value = '已存在同名分组'; return }
  const next = draft(), id = crypto.randomUUID(); next.groups.push({id,name:title,targets:[]})
  if (await persist(next)) { selectedId.value = id; groupName.value = '' }
}
async function renameGroup() {
  const next = draft(), selected = next.groups.find(item => item.id === selectedId.value), title = rename.value.trim()
  if (!selected || !title) return
  if (next.groups.some(item => item.id !== selected.id && item.name === title)) { error.value = '已存在同名分组'; return }
  selected.name = title; await persist(next)
}
async function removeGroup() {
  const next = draft(); next.groups = next.groups.filter(item => item.id !== selectedId.value)
  if (await persist(next)) { selectedId.value = next.groups[0]?.id ?? ''; deleteGroup.value = false }
}
async function addTarget() {
  if (!group.value || saving.value || loading.value) return
  const selected = selectedId.value, owner = currentUser.value?.id
  const target: TrackingTarget = kind.value === 'board' || kind.value === 'index'
    ? {...picker.value,name:picker.value.name ?? ''} : {kind:kind.value,code:code.value.trim(),market:market.value,name:name.value.trim()}
  try {
    validateTrackingTarget(target)
    if (!target.name) {
      saving.value = true
      try { target.name = (await fetchStockNames([{market:target.market,code:target.code}]))[target.code] ?? '' }
      finally { saving.value = false }
      if (!target.name) throw new Error('无法获取标的名称，请核对代码或填写名称后重试')
    }
    if (owner !== currentUser.value?.id || selected !== selectedId.value) return
    const next = draft(), destination = next.groups.find(item => item.id === selected)
    if (!destination) return
    if (destination.targets.some(item => trackingKey(item) === trackingKey(target))) throw new Error('本组已添加此标的')
    destination.targets.push(target)
    if (await persist(next)) { code.value = ''; name.value = '' }
  } catch (e) { if (currentUser.value?.id === owner) error.value = formatError(e) }
}
async function removeTarget(target: TrackingTarget) {
  const next = draft(), selected = next.groups.find(item => item.id === selectedId.value)
  if (!selected) return
  selected.targets = selected.targets.filter(item => trackingKey(item) !== trackingKey(target)); await persist(next)
}
const exchangeNow = () => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date())
async function run() {
  if(unsaved.value){error.value='上一批结果尚未保存，请先重试或导出后放弃重试';return}
  if (!group.value?.targets.length || !periods.value.length || loading.value || saving.value) return
  const selected=book.value.groups.find(item=>item.id===selectedId.value)
  if(!selected){error.value='分组已删除，请选择其他分组；当前展示为上次分析快照';return}
  inspected.value='';page.value=1;error.value='';breadthFilter.value=[]
  const denied=()=>trackingSession.stop('账户或追踪权限已变化，分析已停止')
  await trackingSession.run(selected,book.value.revision,{
    now:exchangeNow,
    members:async(code,signal,owner)=>{
      try{return await fetchBoardMembers(code,100000,signal,owner)}
      catch(e){signal.throwIfAborted();if(e&&typeof e==='object'&&'status' in e&&[401,403,409].includes(Number(e.status))){denied();signal.throwIfAborted()}throw e}
    },
    analyze:(target,chosen,asOf,signal,owner)=>analyzeTrackingTarget(target,chosen,asOf,signal,owner,denied),
  })
}
function cells(row: TrackingAnalysis) { const first = overviewRow(row); return first && !first.error ? periodOverviewCells(first) : null }
function overviewRow(row: TrackingAnalysis) { return breadthFilter.value.length ? row.study?.rows.find(item => item.category===breadthFilter.value[0]!.category) : row.study?.rows.find(item => !item.error) }
function inspectChart(target: TrackingTarget, category: StudyPeriod) { void router.push({path:'/chanlun',query:trackingChartQuery(target,category)}) }
function exportReport() {
  downloadPending()
}
</script>

<template>
  <div class="tracking-view" tabindex="0" aria-label="追踪标的工作区，可上下滚动">
    <section class="tracking-history" aria-label="自动保存与历史记录">
      <p>每批分析结束或主动停止后自动保存到当前账户；重开历史不重新取数。请等待保存成功再关闭或刷新页面。</p>
      <p v-if="archiveSaving" role="status">正在保存本次完整分析…</p>
      <p v-else-if="archiveSaved" role="status">{{ archiveSaved.state==='active'?'本次分析已保存，可展开历史查看。':'服务器已接收，此记录已在回收站；未自动恢复。' }}</p>
      <p v-if="archiveError" role="alert" class="tracking-error">尚未保存：{{ archiveError }}。原结果仍保留。</p>
      <div v-if="unsaved&&!archiveSaving" class="analysis-actions"><button @click="trackingAutoSave.retry()">重试保存</button><button @click="downloadPending">导出完整原结果</button><button @click="trackingAutoSave.clear()">放弃重试（保留已上传内容）</button></div>
      <p v-if="unsaved">本批记录尚未保存，暂不能启动下一批；请先重试，或导出后放弃重试。</p>
      <CloudResearchArchives kind-filter="tracking" :refresh-key="archiveSaved?.id" />
    </section>
    <header class="tracking-header"><div><h2>追踪标的</h2><p>按组管理标的，统一查看量价、严格笔与背离。</p></div><span>{{ book.groups.length }} 个分组 · 当前账户独立保存</span></header>
    <p v-if="error" class="tracking-error" role="alert">{{ error }}</p><p v-if="notice" class="tracking-notice" role="status">{{ notice }}</p>
    <p v-if="analysisError" class="tracking-error" role="alert">{{ analysisError }}</p>
    <div class="tracking-layout">
      <aside class="group-sidebar" aria-label="追踪分组">
        <form @submit.prevent="createGroup"><label for="new-tracking-group">新建分组</label><div class="inline-form"><input id="new-tracking-group" v-model="groupName" maxlength="40" placeholder="例如：新能源" :disabled="saving || corrupt || loading"><button :disabled="saving || corrupt || loading || !groupName.trim()">添加</button></div></form>
        <nav aria-label="选择分组"><button v-for="item in book.groups" :key="item.id" :class="{selected:item.id===selectedId}" :aria-current="item.id === selectedId ? 'page' : undefined" :disabled="saving || loading" @click="selectedId = item.id"><span>{{ item.name }}</span><small>{{ item.targets.length }}</small></button></nav>
        <p class="muted">分组保存标的清单；板块成员在分析时重新展开。分析中可切换其他页面；切换分组前请先停止当前批次。</p>
      </aside>
      <main class="tracking-workspace">
        <div v-if="!group" class="tracking-empty"><h3>建立你的追踪清单</h3><p>先新建分组，再加入个股、板块、指数或场内基金。</p></div>
        <template v-else>
          <header class="group-heading"><div><h3>{{ group.name }}</h3><p>{{ group.targets.length }} 个直接追踪标的 · 板块包含自身及全部成员股</p></div><details><summary>管理分组</summary><form @submit.prevent="renameGroup"><label>分组名称<input v-model="rename" maxlength="40" :placeholder="group.name"></label><button :disabled="saving || loading || !rename.trim()">保存名称</button></form><button :disabled="saving || loading" @click="deleteGroup = true">删除分组…</button><div v-if="deleteGroup" role="alert"><p>删除“{{ group.name }}”及其追踪清单？不影响其他分组。</p><button :disabled="saving" @click="removeGroup">确认删除</button><button @click="deleteGroup = false">取消</button></div></details></header>
          <details class="tracking-add" open><summary>添加追踪标的</summary><fieldset :disabled="saving || loading"><form class="target-form" @submit.prevent="addTarget"><label>标的类型<MacSelect v-model="kind" :options="kinds" :disabled="saving || loading" aria-label="追踪标的类型" /></label><ChanlunTargetPicker v-if="kind==='board'||kind==='index'" v-model="picker" hide-kind /><template v-else><label>证券代码<input v-model="code" inputmode="numeric" maxlength="6" placeholder="六位代码" required></label><label>交易市场<MacSelect v-model="market" :options="marketOptions" :disabled="saving || loading" aria-label="追踪标的市场" /></label><label><span>名称 <small>· 留空自动查询</small></span><input v-model="name" maxlength="80" placeholder="证券简称"></label></template><button :disabled="saving || loading || corrupt">{{ saving ? '保存中…' : '加入本组' }}</button></form></fieldset><p class="muted">基金仅支持沪深场内 ETF、LOF 等；场外基金暂不支持。个股采用前复权，指数、板块和场内基金不复权。</p></details>
          <ul class="target-list" aria-label="本组追踪清单"><li v-for="target in group.targets" :key="trackingKey(target)"><span class="kind-label">{{ trackingLabels[target.kind] }}</span><strong>{{ trackingTitle(target) }}</strong><small>{{ target.kind === 'board' ? '含全部成员股' : target.market }}</small><button :disabled="saving || loading" :aria-label="`移除${trackingTitle(target)}`" @click="removeTarget(target)">移除</button></li></ul>
          <section class="tracking-analysis" aria-label="分组分析">
            <p class="background-note">可切换站内其他页面，返回后继续查看进度与结果。请保留此浏览器标签页；刷新、关闭、退出登录或撤销权限会中断，浏览器休眠也可能暂停执行。</p>
            <p v-if="snapshot && snapshot.revision!==book.revision" class="tracking-notice">分组清单已有更新；下方仍为本批次启动时的标的快照，重新分析才会使用最新清单。</p>
            <div class="analysis-heading"><div><h3>分组缠论分析</h3><p>标的去重，保留所有来源。每个周期最多取 800 根，只分析共同截止前的完整 K 线。</p></div><div class="analysis-actions"><button v-if="loading" @click="stop">停止分析</button><button v-else class="primary-action" :disabled="saving || !!unsaved || !group.targets.length || !periods.length" @click="run">分析本组</button><button :disabled="!rows.length || loading" @click="exportReport">导出结果</button></div></div>
            <fieldset class="period-choices" :disabled="loading"><legend>分析周期</legend><label v-for="period in periodOptions" :key="period"><input v-model="periods" type="checkbox" :value="period">{{ studyLabel(period) }}</label></fieldset>
            <div v-if="phase" class="batch-status" role="status"><div><strong>{{ phase }}</strong><span>{{ completed }} / {{ rows.length }} · 成功 {{ successful }} · 失败 {{ failed }}</span></div><progress :value="completed" :max="rows.length || 1" /><small>共同截止（北京时间）：{{ cutoff }}；成分取自当前查询，不代表历史成员。</small></div>
            <div v-if="issues.length" class="tracking-error" role="alert"><strong>{{ issues.length }} 个板块成员未完整展开，不能视为全组覆盖</strong><p v-for="issue in issues" :key="trackingKey(issue.target)">{{ trackingTitle(issue.target) }}：{{ issue.reason }}</p></div>
            <TrackingBreadth v-if="rows.length" :rows="rows" :periods="periods" :model-value="breadthFilter" @update:model-value="selectBreadth" />
            <div v-if="rows.length" class="result-tools"><label>查找结果<input v-model="query" placeholder="代码、名称或来源板块"></label><fieldset class="status-filters"><legend>状态 · 可多选</legend><label v-for="option in filterOptions" :key="option.value"><input v-model="filter" type="checkbox" :value="option.value">{{ option.label }}</label><button v-if="filter.length" type="button" @click="filter=[]">清除状态</button></fieldset><span>{{ visibleRows.length }} 个匹配标的</span></div>
            <div v-if="rows.length" ref="resultScroll" class="result-scroll" tabindex="0" role="region" aria-label="追踪分析表，独立上下及左右滚动"><table><thead><tr><th>标的 / 来源</th><th>状态 / 已收盘截止</th><th>均线 / 价格</th><th>成交量</th><th>MACD</th><th>严格笔与当前方向</th><th>背离</th><th>买卖点</th></tr></thead><tbody><template v-for="row in pageRows" :key="trackingKey(row.target)"><tr><th><button class="inspect-button" @click="inspected = inspected === trackingKey(row.target) ? '' : trackingKey(row.target)" :aria-expanded="inspected === trackingKey(row.target)">{{ trackingTitle(row.target) }}</button><small>{{ trackingLabels[row.target.kind] }} · {{ row.target.market }}</small><small>{{ row.sources.join('、') }}</small></th><td><strong :class="{'tracking-error':row.state==='error'}">{{ statusLabel[row.state] }}</strong><small v-if="overviewRow(row)?.last_closed_at">{{ studyLabel(overviewRow(row)!.category) }} · {{ overviewRow(row)!.last_closed_at }}</small><p v-if="row.error" class="tracking-error">{{ row.error }}</p><small v-if="row.study">展开标的查看所有周期</small></td><template v-if="cells(row)"><td v-for="(cell,index) in cells(row)!.slice(0,6)" :key="index"><p v-for="(line,i) in cell.slice(0,3)" :key="i">{{ line }}</p><small v-if="cell.length>3">其余 {{ cell.length-3 }} 条见展开内容</small></td></template><td v-else colspan="6" class="muted">{{ row.state==='error' ? '本项未得出结论' : row.state==='cancelled' ? '未完成，不计入成功' : '等待分析结果…' }}</td></tr><tr v-if="inspected===trackingKey(row.target)"><td colspan="8" class="expanded-result"><div class="analysis-actions"><strong>{{ trackingTitle(row.target) }}</strong><button v-for="period in periods" :key="period" @click="inspectChart(row.target,period)">打开{{ studyLabel(period) }}图表 ↗</button></div><p class="muted">打开图表将按相同标的、周期和复权重新查询；不是本批次原始快照回放。</p><MultiPeriodOverviewTable :periods="periods" :rows="row.study?.rows ?? []" :errors="{}" :loading="row.state==='running'" @inspect="period => inspectChart(row.target,period)" /></td></tr></template></tbody></table></div>
            <p v-if="rows.length && !visibleRows.length" class="tracking-empty muted" role="status">没有符合当前筛选条件的标的；可清除筛选或修改搜索条件。</p>
            <div v-if="rows.length" class="analysis-actions"><button :disabled="page <= 1" @click="page--">上一页</button><span class="muted">{{ page }} / {{ pageCount }} 页 · 每页 50 个，分析覆盖全部成员</span><button :disabled="page >= pageCount" @click="page++">下一页</button></div>
            <p v-else class="tracking-empty muted">添加标的后点击“分析本组”。大板块需要较长时间，切换站内页面不会取消分析。</p>
          </section>
        </template>
      </main>
    </div>
  </div>
</template>

<style scoped>
.breadth-section{margin:20px 0}.breadth-scroll{overflow:auto;margin-top:12px}.breadth-scroll table{width:100%;min-width:600px;border-collapse:collapse;font-size:11px}.breadth-scroll th,.breadth-scroll td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}.breadth-scroll thead th{font-weight:500;color:var(--text-muted)}
.tracking-view{padding:24px;min-width:0;color:var(--text)}.tracking-header,.group-heading,.analysis-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.tracking-header{padding-bottom:22px;border-bottom:1px solid var(--border)}h2{font-size:22px;margin:0 0 8px}h3{font-size:15px;margin:0 0 8px}p{margin:6px 0;line-height:1.7}small,.muted,.tracking-header>span,header p,.analysis-heading p{color:var(--text-muted);font-size:11px;line-height:1.7}.tracking-layout{display:grid;grid-template-columns:200px minmax(0,1fr);gap:28px;padding-top:24px}.group-sidebar{border-right:1px solid var(--border);padding-right:20px}.inline-form{display:flex;gap:6px;margin-top:8px}input{min-width:0;width:100%}button{font-size:12px;padding:7px 12px;white-space:nowrap;transition:background .15s,border-color .15s}.group-sidebar nav{display:grid;gap:4px;margin:20px 0}.group-sidebar nav button{display:flex;justify-content:space-between;align-items:center;text-align:left;background:transparent;border:1px solid transparent;min-width:0;white-space:normal}.group-sidebar nav button span{overflow-wrap:anywhere}.group-sidebar nav button.selected{color:var(--accent);background:rgba(68,150,235,.09);border-color:rgba(68,150,235,.2)}label{font-size:11px;color:var(--text-muted);display:grid;gap:8px}.tracking-workspace{min-width:0}.group-heading>div{min-width:0;overflow-wrap:anywhere}.group-heading details{min-width:150px;max-width:340px}summary{cursor:pointer;font-size:12px;color:var(--text-dim);padding:8px 0}.group-heading form{display:flex;gap:8px;align-items:end;padding:8px 0}.tracking-add{padding:12px 0 20px;margin-top:12px;border-bottom:1px solid var(--border)}fieldset{border:0;padding:0;margin:0;min-width:0}.target-form{display:flex;flex-wrap:wrap;gap:14px;align-items:end;margin:10px 0}.target-form>label{flex:1 1 125px;max-width:220px}.target-form>.target-picker{flex:1 1 260px;margin:0;max-width:440px}.target-list{list-style:none;padding:0;margin:12px 0 28px;max-height:280px;overflow:auto}.target-list li{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);font-size:12px}.target-list strong{font-weight:500;overflow-wrap:anywhere}.target-list button{margin-left:auto;background:transparent;color:var(--text-muted);font-size:11px}.kind-label{font-size:10px;color:var(--text-muted);min-width:48px}.analysis-heading{align-items:center}.analysis-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.primary-action{color:var(--accent);border-color:rgba(68,150,235,.4)}.period-choices{display:flex;flex-wrap:wrap;gap:16px;margin:18px 0}.period-choices legend{font-size:11px;color:var(--text-muted);margin-bottom:10px}.period-choices label{display:flex;align-items:center;gap:6px;cursor:pointer}.period-choices input{width:auto;accent-color:var(--accent)}.batch-status{padding:14px 0;border-top:1px solid var(--border);font-size:12px}.batch-status>div{display:flex;justify-content:space-between;gap:10px}.batch-status progress{width:100%;height:4px;accent-color:var(--accent);margin:12px 0}.batch-status span{color:var(--text-muted);font-variant-numeric:tabular-nums}.result-tools{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin:16px 0}.result-tools>label:first-child{width:260px}.result-tools>label:nth-child(2){width:160px}.result-tools>span{font-size:11px;color:var(--text-muted);padding-bottom:9px}.result-scroll{overflow:auto;max-width:100%;border:1px solid var(--border);border-radius:10px;max-height:760px}.result-scroll>table{border-collapse:separate;border-spacing:0;width:100%;min-width:1480px;font-size:11px;line-height:1.65}.result-scroll th,.result-scroll td{padding:14px;text-align:left;vertical-align:top;border-bottom:1px solid var(--border);min-width:180px;max-width:320px;overflow-wrap:anywhere}.result-scroll thead th{position:sticky;top:0;z-index:2;background:var(--bg-panel,#1c1e23);font-weight:500}.result-scroll tbody th{position:sticky;left:0;background:var(--bg-panel,#1c1e23);z-index:1;min-width:180px;max-width:230px}.result-scroll small{display:block;margin-top:6px}.inspect-button{white-space:normal;padding:0;background:transparent;border:0;text-align:left;color:var(--accent)}.expanded-result{background:rgba(128,128,128,.035)}.tracking-error{color:#e79292!important;font-size:12px;overflow-wrap:anywhere}.tracking-notice{color:var(--accent);font-size:12px}.tracking-empty{padding:34px 0}.tracking-view :focus-visible{outline:2px solid var(--accent);outline-offset:3px}@media(max-width:1000px){.tracking-layout{grid-template-columns:160px minmax(0,1fr);gap:18px}.analysis-heading{flex-direction:column;align-items:stretch}}@media(max-width:640px){.tracking-view{padding:16px 12px}.tracking-header{flex-direction:column;gap:8px}.tracking-layout{display:block;padding-top:16px}.group-sidebar{border-right:0;border-bottom:1px solid var(--border);padding:0 0 14px;margin-bottom:20px}.group-sidebar nav{display:flex;overflow-x:auto;margin:12px 0}.group-sidebar nav button{flex-shrink:0;gap:10px}.group-sidebar>.muted{display:none}.group-heading{flex-direction:column;gap:6px}.group-heading details{width:100%;max-width:none}.target-form>label{max-width:none}.target-list li{flex-wrap:wrap;gap:8px}.target-list strong{flex:1;min-width:140px}.batch-status>div{flex-direction:column}.result-tools>label:first-child{width:100%}.analysis-actions button{min-height:36px}}@media(prefers-reduced-motion:reduce){button{transition:none}}

.tracking-view{box-sizing:border-box;touch-action:pan-x pan-y}.result-scroll{height:clamp(260px,60dvh,760px);max-height:none;overscroll-behavior:contain;touch-action:pan-x pan-y;scroll-padding-top:48px}.status-filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;flex:1 1 300px}.status-filters legend{font-size:11px;color:var(--text-muted);margin-bottom:8px}.status-filters label{display:flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid var(--border);border-radius:7px;cursor:pointer}.status-filters label:has(input:checked){color:var(--accent);background:rgba(68,150,235,.09);border-color:rgba(68,150,235,.3)}.status-filters input{width:14px;height:14px;min-height:0;margin:0;accent-color:var(--accent)}.status-filters button{font-size:11px;background:transparent}.result-scroll:focus-visible{outline-offset:-2px}@media(max-width:640px){.result-scroll{height:58dvh;min-height:260px}.status-filters label{min-height:36px}}
</style>

<style scoped>
/* The desktop app clips its route outlet; this route owns its vertical scroll. */
.tracking-history{margin-bottom:22px;padding-bottom:16px;border-bottom:1px solid var(--border)}.tracking-history>p{font-size:11px;color:var(--text-muted)}
.tracking-view{height:100%;min-height:0;overflow-y:auto;overflow-x:hidden;overscroll-behavior-y:contain;scrollbar-gutter:stable;padding-bottom:max(32px,env(safe-area-inset-bottom))}
.tracking-layout,.tracking-workspace,.tracking-analysis,.analysis-heading>div{min-width:0}
.tracking-view p,.tracking-view small,.batch-status strong,.analysis-actions strong{overflow-wrap:anywhere;white-space:normal}
.background-note{font-size:11px;color:var(--text-muted);padding:10px 0 16px;margin:0;line-height:1.8}
.batch-status>div{flex-wrap:wrap}.batch-status small{display:block}
.result-scroll{max-height:min(760px,65dvh);scrollbar-gutter:stable;overscroll-behavior-x:contain;overscroll-behavior-y:contain}
.breadth-scroll{max-width:100%;overscroll-behavior-x:contain}
.result-tools>label{max-width:100%}.analysis-actions{min-width:0;max-width:100%}
.result-scroll:focus-visible,.breadth-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:640px){.tracking-header>span{overflow-wrap:anywhere}.result-scroll{max-height:62dvh}.analysis-heading{gap:12px}}
</style>


<style scoped>
/* The desktop app clips its route outlet; this route owns its vertical scroll. */
.tracking-history{margin-bottom:22px;padding-bottom:16px;border-bottom:1px solid var(--border)}.tracking-history>p{font-size:11px;color:var(--text-muted)}
.tracking-view{height:100%;min-height:0;overflow-y:auto;overflow-x:hidden;overscroll-behavior-y:contain;scrollbar-gutter:stable;padding-bottom:max(32px,env(safe-area-inset-bottom))}
.tracking-layout,.tracking-workspace,.tracking-analysis,.analysis-heading>div{min-width:0}
.tracking-view p,.tracking-view small,.batch-status strong,.analysis-actions strong{overflow-wrap:anywhere;white-space:normal}
.background-note{font-size:11px;color:var(--text-muted);padding:10px 0 16px;margin:0;line-height:1.8}
.batch-status>div{flex-wrap:wrap}.batch-status small{display:block}
.result-scroll{max-height:min(760px,65dvh);scrollbar-gutter:stable;overscroll-behavior-x:contain;overscroll-behavior-y:contain}
.breadth-scroll{max-width:100%;overscroll-behavior-x:contain}
.result-tools>label{max-width:100%}.analysis-actions{min-width:0;max-width:100%}
.result-scroll:focus-visible,.breadth-scroll:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media(max-width:640px){.tracking-header>span{overflow-wrap:anywhere}.result-scroll{max-height:62dvh}.analysis-heading{gap:12px}}
</style>
