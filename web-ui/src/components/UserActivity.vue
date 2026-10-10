<script setup lang="ts">
import {onMounted,onUnmounted,ref,watch} from 'vue'
import {activityDetails,activityDuration,activityTime,activityTargetLabel,activityMarketLabel,type ActivityCodeGroup,type ActivityTarget,type ActivityEvent,type ActivityLocation,type ActivityUser} from '../activity'
import {activityTargetNames} from '../activity-target-names'
import type {AccountUser} from '../types'
import MacSelect from './MacSelect.vue'
const props=defineProps<{users:AccountUser[]}>()
const days=ref('7'),owner=ref(''),kind=ref(''),error=ref(''),loading=ref(false),geoBusy=ref(0)
const summaries=ref<ActivityUser[]>([]),events=ref<ActivityEvent[]>([]),cursor=ref<number|null>(null),offset=ref<number|null>(null)
const view=ref('events'),codeInput=ref(''),codeFilter=ref(''),groups=ref<ActivityCodeGroup[]>([]),groupOffset=ref<number|null>(null)
const names=ref<Record<string,string>>({}),namesLoading=ref(false)
let generation=0,controller:AbortController|undefined
let nameController:AbortController|undefined
async function enrich(targets:ActivityTarget[],stamp:number){
  nameController?.abort();nameController=new AbortController()
  const missing=targets.filter(target=>!names.value[target.key]);if(!missing.length){namesLoading.value=false;return}
  namesLoading.value=true
  try{const found=await activityTargetNames(missing,nameController.signal);if(stamp===generation)names.value={...names.value,...found}}
  finally{if(stamp===generation)namesLoading.value=false}
}
function applyCode(){
  const value=codeInput.value.trim()
  if(value&&!/^[A-Za-z0-9?_.:-]{1,81}$/.test(value)){error.value='请输入完整代码，或市场:代码（例如 SZ:000001）';return}
  codeFilter.value=value;if(value)kind.value='query'
}
function inspectCode(target:ActivityTarget){codeInput.value=target.key;codeFilter.value=target.key;kind.value='query';view.value='events'}
async function request<T>(path:string,init?:RequestInit):Promise<T>{const res=await fetch(`/api/v1${path}`,{credentials:'same-origin',...init});if(!res.ok){let message='记录读取失败';try{message=(await res.json()).detail||message}catch{}throw Error(String(message))}return res.json()}
async function load(append=false){
  if(append&&(loading.value||(view.value==='codes'?groupOffset.value==null:cursor.value==null)))return
  const stamp=++generation;controller?.abort();controller=new AbortController();loading.value=true;error.value=''
  nameController?.abort();namesLoading.value=false
  const filters=new URLSearchParams({days:days.value});if(owner.value)filters.set('user_id',owner.value)
  try{
    if(!append){const result=await request<{items:ActivityUser[];next_offset:number|null}>(`/admin/activity/summary?${filters}`,{signal:controller.signal});if(stamp!==generation)return;summaries.value=result.items;offset.value=result.next_offset}
    if(codeFilter.value)filters.set('code',codeFilter.value)
    if(view.value==='codes'){
      if(append&&groupOffset.value!==null)filters.set('offset',String(groupOffset.value))
      const result=await request<{items:ActivityCodeGroup[];next_offset:number|null}>(`/admin/activity/codes?${filters}`,{signal:controller.signal});if(stamp!==generation)return
      groups.value=append?[...groups.value,...result.items]:result.items;groupOffset.value=result.next_offset
      void enrich(groups.value,stamp);return
    }
    if(kind.value)filters.set('kind',kind.value);if(append&&cursor.value)filters.set('before',String(cursor.value))
    const result=await request<{items:ActivityEvent[];next_cursor:number|null}>(`/admin/activity/events?${filters}`,{signal:controller.signal});if(stamp!==generation)return
    events.value=append?[...events.value,...result.items]:result.items;cursor.value=result.next_cursor
    void enrich(events.value.flatMap(item=>item.targets||[]),stamp)
  }catch(e){if(stamp===generation)error.value=e instanceof Error?e.message:'记录读取失败'}finally{if(stamp===generation)loading.value=false}
}
async function moreUsers(){if(offset.value==null||loading.value)return;const stamp=generation;loading.value=true;try{const filters=new URLSearchParams({days:days.value,offset:String(offset.value)});if(owner.value)filters.set('user_id',owner.value);const result=await request<{items:ActivityUser[];next_offset:number|null}>(`/admin/activity/summary?${filters}`,{signal:controller?.signal});if(stamp===generation){summaries.value.push(...result.items);offset.value=result.next_offset}}catch(e){if(stamp===generation)error.value=String(e)}finally{if(stamp===generation)loading.value=false}}
async function locate(item:ActivityEvent){if(geoBusy.value)return;const stamp=generation;geoBusy.value=item.id;try{const result=await request<ActivityLocation>(`/admin/activity/events/${item.id}/location`,{method:'POST',signal:controller?.signal});if(stamp===generation)for(const record of events.value)if(record.ip===item.ip)record.location=result}catch(e){if(stamp===generation)error.value=String(e)}finally{geoBusy.value=0}}
watch([days,owner,kind,view,codeFilter],()=>{summaries.value=[];events.value=[];groups.value=[];cursor.value=null;groupOffset.value=null;offset.value=null;void load()})
onMounted(()=>void load());onUnmounted(()=>{generation++;controller?.abort();nameController?.abort()})
</script>
<template>
  <section class="activity-section" aria-labelledby="activity-heading" :aria-busy="loading">
    <header><div><h2 id="activity-heading">用户活动</h2><p>活跃时长、登录来源与用户主动查询 · 北京时间</p></div><button class="sm" :disabled="loading" @click="load()">刷新活动</button></header>
    <p class="query-scope">仅统计用户主动发起的查询；自动刷新、名称补全、预加载及自动计算不包含在内。旧版未区分来源的查询保留原数据，不计入此处。</p>
    <div class="filters"><MacSelect v-model="days" :options="[{value:'1',label:'今天'},{value:'7',label:'最近 7 天'},{value:'30',label:'最近 30 天'},{value:'90',label:'最近 90 天'}]" aria-label="活动时间范围"/><MacSelect v-model="owner" :options="[{value:'',label:'全部用户'},...props.users.map(user=>({value:user.id,label:user.username}))]" aria-label="活动用户"/><MacSelect v-model="kind" :disabled="view==='codes'||!!codeFilter" :options="[{value:'',label:'全部记录'},{value:'login',label:'登录记录'},{value:'query',label:'查询记录'}]" aria-label="活动记录类型"/></div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="table-scroll" tabindex="0" aria-label="用户活跃汇总"><table><thead><tr><th>用户</th><th>活跃时长（估算）</th><th>登录次数</th><th>主动查询请求</th><th>最后活动</th></tr></thead><tbody><tr v-for="user in summaries" :key="user.id"><td><button class="username" @click="owner=user.id">{{ user.username }}</button><small v-if="user.recently_active" class="online">近期活跃</small></td><td class="numeric">{{ activityDuration(user.active_seconds) }}</td><td class="numeric">{{ user.logins }}</td><td class="numeric">{{ user.queries }}</td><td>{{ activityTime(user.last_seen) }}</td></tr></tbody></table></div>
    <button v-if="offset!==null" class="sm more" :disabled="loading" @click="moreUsers">更多用户</button>
    <div class="query-toolbar">
      <div class="view-switch" role="group" aria-label="查询记录显示方式"><button class="sm" :aria-pressed="view==='events'" @click="view='events'">活动明细</button><button class="sm" :aria-pressed="view==='codes'" @click="view='codes';kind='query'">按代码分类</button></div>
      <form class="code-filter" @submit.prevent="applyCode"><label for="activity-code">查询代码</label><input id="activity-code" v-model="codeInput" maxlength="81" placeholder="如 300750 或 SZ:000001"><button class="sm" type="submit">筛选</button><button v-if="codeFilter" class="sm" type="button" @click="codeInput='';codeFilter=''">清除</button></form>
    </div>
    <p class="query-scope">{{ namesLoading?'正在补全标的名称…':'名称为当前简称；未取得时保留代码，可刷新重试。' }} 用户活跃汇总不受代码筛选影响。</p>
    <template v-if="view==='codes'">
      <div class="records-heading"><h3>按查询代码分类</h3><span>{{ groups.length }} 个已载入</span></div>
      <p class="query-scope">按市场与代码区分，同一请求内重复标的只计一次；批量请求会分别计入各标的。统计所选时间及用户范围内全部保留的主动查询明细，无代码的概览请求不归类。</p>
      <div class="table-scroll" tabindex="0" aria-label="按查询代码汇总"><table><thead><tr><th>代码－名称</th><th>市场</th><th>查询请求</th><th>涉及用户</th><th>最近查询</th></tr></thead><tbody><tr v-for="group in groups" :key="group.key"><td><button class="username target-link" @click="inspectCode(group)">{{ activityTargetLabel(group,names) }}</button></td><td>{{ activityMarketLabel(group.market) }}</td><td class="numeric">{{ group.queries }}</td><td class="numeric">{{ group.users }}</td><td>{{ activityTime(group.last_seen) }}</td></tr></tbody></table></div>
      <p v-if="!groups.length" class="empty" role="status">{{ loading?'正在读取…':'此范围内没有包含查询代码的主动记录。' }}</p>
      <button v-if="groupOffset!==null" class="sm more" :disabled="loading" @click="load(true)">更多查询代码</button>
    </template>
    <template v-else>
    <div class="records-heading"><h3>活动明细</h3><span>{{ events.length }} 条已载入</span></div>
    <p v-if="!events.length" class="empty" role="status">{{ loading?'正在读取…':'此时间范围内暂无记录；功能启用前的活动不会补造。' }}</p>
    <ol class="event-list"><li v-for="item in events" :key="item.id"><div class="event-head"><strong>{{ item.username }}</strong><span>{{ item.feature }}</span><span class="outcome">{{ item.outcome==='accepted'?'请求已受理':'请求未完成' }}</span><time>{{ activityTime(item.occurred) }}</time></div><div v-if="item.targets?.length" class="event-targets"><button v-for="target in item.targets" :key="target.key" class="username target-link" @click="inspectCode(target)">{{ activityTargetLabel(target,names) }} <small>{{ activityMarketLabel(target.market) }}</small></button></div><p v-if="item.kind==='query'" class="query-info">{{ activityDetails(item.details) }}</p><div class="ip-row"><code>{{ item.ip||'IP 未取得' }}</code><span>{{ item.location?.label||'归属地待查询' }}{{ item.location?.isp?` · ${item.location.isp}`:'' }}</span><button v-if="item.ip&&!['local','ok'].includes(item.location?.state||'')" class="sm" :disabled="!!geoBusy" @click="locate(item)">{{ geoBusy===item.id?'查询中…':'查询归属地' }}</button><small v-if="item.location?.checked_at">查询于 {{ activityTime(item.location.checked_at) }}</small></div></li></ol>
    <button v-if="cursor!==null" class="sm more" :disabled="loading" @click="load(true)">加载更早记录</button>
    </template>
    <details class="activity-notes">
      <summary>统计口径与隐私范围</summary>
      <p>页面可见、获得焦点且 60 秒内有操作时，每 15 秒报告一次。以服务器时间估算，多标签／设备合并计时；休眠或中断超过 45 秒不补计。不是精确考勤，客户端可拒绝或伪造心跳。</p>
      <p>只记录登录及明确标记为用户主动发起的受支持查询，含标的、周期、复权及功能。自动刷新、名称补全、预加载、自动多周期计算和任务轮询不记录；账户内容、密码、令牌、策略源码和完整行情也不记录。一次主动操作可包含取行情与分析等多个主要请求，计数不是点击次数。“已受理”不等于分析结论有效或任务完成。</p>
      <p>来源标记用于产品使用统计，不是防篡改审计或身份认证；旧客户端未标记的请求不计入。旧版混合查询保留原数据，但不在本列表和主动查询次数中展示。登录和活跃时长口径不变。</p>
      <p>代码分类根据原记录中的市场和代码生成，不猜测缺失市场，不修改历史记录。批量请求仅包含原记录保留的前 100 个条目；各代码次数相加可超过请求总数。简称按当前名称补全，每次最多 200 个标的；未取得的名称可按代码筛选后刷新重试，不影响记录和分类。名称补全请求不计入主动查询。</p>
      <p>明细最多保留最近 90 天／10 万条，以先达到者为准；汇总保留 90 天，写入时清理。IP 使用服务器可信代理配置处理后的连接地址；内网地址不外查。归属地按需通过 <a href="https://ipwhois.io/documentation" target="_blank" rel="noopener noreferrer">ipwho.is</a> 查询，仅发送 IP，成功缓存 30 天；结果可能反映 VPN 或代理出口，不代表用户实际所在地。</p>
    </details>
  </section>
</template>
<style scoped>
.query-toolbar{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px;margin-top:24px}.view-switch{display:flex;gap:4px}.view-switch button[aria-pressed="true"]{color:var(--accent);border-color:var(--accent)}.code-filter{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px}.code-filter input{min-width:0;width:205px;height:32px;font-size:12px}.code-filter label{color:var(--text-muted)}.event-targets{display:flex;gap:8px 18px;flex-wrap:wrap;margin-top:12px;max-height:180px;overflow:auto}.target-link{font-size:12px!important;text-align:left;line-height:1.7;overflow-wrap:anywhere;transition:color .15s}.target-link small{color:var(--text-muted);font-size:10px;margin-left:4px}.username:focus-visible{outline:2px solid var(--accent);outline-offset:4px}@media(max-width:600px){.code-filter{width:100%}.code-filter input{flex:1;width:120px}.query-toolbar{align-items:flex-start}.view-switch button{min-height:36px}}@media(prefers-reduced-motion:reduce){.target-link{transition:none}}
.query-scope{font-size:12px;color:var(--text-muted);line-height:1.8;margin-top:12px}
.activity-section{min-width:0;padding:8px 2px 24px}header,.records-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}h2{font-size:17px;font-weight:600}header p,.activity-notes p{font-size:12px;color:var(--text-muted);line-height:1.8}header p{margin-top:6px}header button{flex-shrink:0}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0 18px}.filters>*{width:180px;max-width:100%}.table-scroll{overflow:auto;max-width:100%;border-block:1px solid var(--border)}table{width:100%;border-collapse:collapse;font-size:12px;min-width:640px}th,td{padding:12px 14px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--border)}th{font-size:11px;color:var(--text-muted);font-weight:500}.numeric{font-variant-numeric:tabular-nums}.username{background:none;border:0;color:var(--text);padding:0;font:inherit;cursor:pointer}.username:hover{color:var(--accent)}.online{display:inline-block;margin-left:8px;color:var(--success);font-size:10px}.records-heading{margin:28px 0 8px}h3{font-size:13px}.records-heading span,time,.outcome{font-size:11px;color:var(--text-muted)}.event-list{list-style:none;padding:0}.event-list li{border-bottom:1px solid var(--border);padding:16px 0}.event-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12px}.event-head time{margin-left:auto;font-variant-numeric:tabular-nums}.event-head strong{font-weight:550}.query-info{font-size:12px;line-height:1.8;color:var(--text-muted);margin:9px 0;overflow-wrap:anywhere;max-height:130px;overflow:auto}.ip-row{display:flex;align-items:center;gap:8px 12px;flex-wrap:wrap;font-size:11px;color:var(--text-muted);margin-top:8px;overflow-wrap:anywhere}.ip-row code{font-size:11px;color:var(--text)}.ip-row small{font-size:10px}.more{display:block;margin:16px 0 0 auto}.activity-notes{margin-top:24px;padding-top:14px;border-top:1px solid var(--border)}summary{font-size:12px;color:var(--text-muted);cursor:pointer}.activity-notes p{margin:10px 0}.error{color:var(--danger);font-size:12px}.empty{font-size:12px;color:var(--text-muted);padding:24px 0}.table-scroll:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:600px){.filters>*{flex:1;min-width:125px}.event-head time{width:100%;margin:0}.event-head .outcome{margin-left:auto}.filters{gap:8px}header{align-items:flex-start}header p{font-size:11px}}
</style>
