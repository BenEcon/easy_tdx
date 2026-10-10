<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { fetchAuditRecords, formatError } from '../api'
import { auditActions, auditDescription, auditOutcomes, auditTime, type AuditRecord } from '../security-audit'
import MacSelect from './MacSelect.vue'

const records = ref<AuditRecord[]>([])
const action = ref('')
const outcome = ref('')
const cursor = ref<number | null>(null)
const loading = ref(false)
const error = ref('')
const retention = ref(10000)
let generation = 0
const actionOptions = [
  { value: '', label: '全部操作' },
  ...Object.entries(auditActions).map(([value, label]) => ({ value, label })),
]
const outcomeOptions = [
  { value: '', label: '全部结果' },
  ...Object.entries(auditOutcomes).map(([value, label]) => ({ value, label })),
]

async function load(append = false) {
  if (append && (loading.value || cursor.value == null)) return
  const requestId = ++generation
  loading.value = true
  error.value = ''
  if (!append) { records.value = []; cursor.value = null }
  try {
    const page = await fetchAuditRecords({
      action: action.value || undefined, outcome: outcome.value || undefined,
      before: append ? cursor.value ?? undefined : undefined, limit: 50,
    })
    if (requestId !== generation) return
    records.value = append ? [...records.value, ...page.items] : page.items
    cursor.value = page.next_cursor
    retention.value = page.retention_limit
  } catch (e) {
    if (requestId === generation) error.value = formatError(e)
  } finally {
    if (requestId === generation) loading.value = false
  }
}

watch([action, outcome], () => load())
onMounted(() => load())
onUnmounted(() => { generation++ })
</script>

<template>
  <section class="audit-section" aria-labelledby="audit-title" :aria-busy="loading">
    <header class="audit-heading">
      <div><h2 id="audit-title">操作记录</h2><p>账户安全与节点维护记录 · 时间均为北京时间</p></div>
      <button class="sm" :disabled="loading" @click="load()">刷新记录</button>
    </header>
    <div class="audit-filters">
      <MacSelect v-model="action" :options="actionOptions" aria-label="筛选操作类型" />
      <MacSelect v-model="outcome" :options="outcomeOptions" aria-label="筛选操作结果" />
      <span>{{ records.length }} 条已载入</span>
    </div>
    <p v-if="error" role="alert" class="audit-error">{{ error }}</p>
    <p v-if="!records.length" role="status" class="audit-empty">{{ loading ? '正在读取记录…' : error ? '记录未能载入，请重试。' : '此筛选条件下暂无记录' }}</p>
    <div v-else class="audit-table-wrap">
      <table>
        <thead><tr><th scope="col">时间</th><th scope="col">操作</th><th scope="col">操作人</th><th scope="col">对象或变更</th><th scope="col">结果</th></tr></thead>
        <tbody>
          <tr v-for="item in records" :key="item.id">
            <td class="audit-date"><time :datetime="item.occurred_at">{{ auditTime(item.occurred_at) }}</time></td>
            <td class="audit-action">{{ auditActions[item.action] ?? '其他操作' }}</td>
            <td class="audit-actor"><span class="mobile-label">操作人</span>{{ item.actor_name ?? (item.action === 'login' && item.outcome === 'denied' ? '未认证' : '系统') }}</td>
            <td class="audit-description">{{ auditDescription(item) }}</td>
            <td class="audit-outcome" :data-outcome="item.outcome"><span aria-hidden="true">●</span>{{ auditOutcomes[item.outcome] ?? '未知' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <footer class="audit-footer">
      <small>最多保留最近 {{ retention.toLocaleString() }} 条；不记录密码或会话令牌。</small>
      <button v-if="cursor != null" class="sm" :disabled="loading" @click="load(true)">{{ loading ? '正在读取…' : '加载更早记录' }}</button>
    </footer>
  </section>
</template>

<style scoped>
.audit-section{min-width:0;padding:8px 2px 24px}.audit-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:8px 0 22px}.audit-heading h2{font-size:17px;font-weight:600;letter-spacing:-.02em}.audit-heading p{margin:6px 0 0;color:var(--text-muted);font-size:12px;line-height:1.6}.audit-heading button{flex-shrink:0}.audit-filters{display:flex;align-items:center;gap:10px;padding-bottom:16px}.audit-filters>:first-child{width:200px}.audit-filters>:nth-child(2){width:140px}.audit-filters>span{margin-left:auto;font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums}.audit-table-wrap{overflow:auto;min-width:0}table{width:100%;border-collapse:collapse;text-align:left;font-size:12px}th{font-size:11px;font-weight:500;color:var(--text-muted);padding:10px 12px;border-bottom:1px solid var(--border)}td{padding:14px 12px;border-bottom:1px solid var(--border);line-height:1.65;vertical-align:top}tr{transition:background .12s}tbody tr:hover{background:rgba(255,255,255,.025)}.audit-date{white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--text-muted);font-size:11px}.audit-action{font-weight:500;white-space:nowrap}.audit-description{color:var(--text-muted);overflow-wrap:anywhere}.audit-outcome{white-space:nowrap;text-align:right;font-size:11px}.audit-outcome span{margin-right:6px;font-size:7px;color:var(--text-muted)}.audit-outcome[data-outcome="success"] span{color:var(--success)}.audit-outcome[data-outcome="failed"],.audit-outcome[data-outcome="denied"]{color:var(--warning,#d9b879)}.audit-outcome[data-outcome="failed"] span,.audit-outcome[data-outcome="denied"] span{color:currentColor}.audit-empty{padding:52px 16px;text-align:center;color:var(--text-muted);font-size:12px}.audit-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:18px}.audit-footer small{color:var(--text-muted);font-size:11px;line-height:1.7}.audit-footer button{flex-shrink:0}.audit-error{color:var(--danger,#ff8c84);font-size:12px;margin:12px 0}.mobile-label{display:none}@media(max-width:640px){.audit-filters{flex-wrap:wrap}.audit-filters>:first-child{flex:1;min-width:160px}.audit-filters>:nth-child(2){width:120px}.audit-filters>span{width:100%;margin:0}.audit-heading{align-items:flex-start}.audit-heading p{font-size:11px}.audit-table-wrap{overflow:visible}table,tbody{display:block}thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}tbody tr{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 12px;padding:14px 0;border-bottom:1px solid var(--border)}td{padding:0;border:0}.audit-date{grid-column:1;grid-row:1}.audit-outcome{grid-column:2;grid-row:1}.audit-action{grid-column:1/-1;grid-row:2}.audit-actor{grid-column:1/-1;grid-row:3;font-size:11px;color:var(--text-muted)}.audit-description{grid-column:1/-1;grid-row:4;font-size:11px}.mobile-label{display:inline;margin-right:8px;color:var(--text-dim)}.audit-footer{align-items:flex-start;flex-direction:column}.audit-footer button{align-self:flex-end}}@media(prefers-reduced-motion:reduce){tr{transition:none}}
</style>
