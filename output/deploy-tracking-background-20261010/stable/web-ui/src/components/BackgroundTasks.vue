<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { cancelTask, deleteTask, fetchTask, fetchTaskList, formatError } from '../api'
import { isTaskFailure, isTaskTerminal, taskElapsed, taskLabels, taskContextNote, taskStatusLabel, taskStorageNote } from '../task-state'
import type { TaskSummary } from '../types'

const tasks = ref<TaskSummary[]>([])
const loading = ref(false)
const error = ref('')
const pending = ref(new Set<string>())
const details = ref<Record<string, string>>({})
const storage = ref<'memory' | 'persistent'>()
const deleting = ref<string | null>(null)
let alive = true
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined

function schedule() {
  clearTimeout(timer)
  if (alive) timer = setTimeout(() => void refresh(), 5000)
}

async function refresh(manual = false) {
  if (loading.value || !alive) return
  if (!manual && document.hidden) { schedule(); return }
  const current = ++generation
  loading.value = true
  try {
    const result = await fetchTaskList(20)
    if (!alive || current !== generation) return
    tasks.value = result.tasks
    storage.value = result.storage
    error.value = ''
  } catch (e) {
    if (alive && current === generation) error.value = formatError(e)
  } finally {
    if (alive) { loading.value = false; schedule() }
  }
}

async function stop(task: TaskSummary) {
  if (pending.value.has(task.task_id)) return
  pending.value.add(task.task_id)
  error.value = ''
  try {
    const state = await cancelTask(task.task_id)
    if (!alive) return
    // Ignore a list response started before cancellation; it may be stale.
    generation++
    tasks.value = tasks.value.map(item => item.task_id === task.task_id ? { ...item, ...state } : item)
    if (state.error) details.value[task.task_id] = state.error
  } catch (e) { if (alive) error.value = formatError(e) }
  finally { if (alive) pending.value.delete(task.task_id) }
}

async function remove(task: TaskSummary) {
  if (pending.value.has(task.task_id)) return
  pending.value.add(task.task_id)
  error.value = ''
  try {
    await deleteTask(task.task_id)
    if (!alive) return
    generation++
    tasks.value = tasks.value.filter(item => item.task_id !== task.task_id)
    delete details.value[task.task_id]
    deleting.value = null
  } catch (e) { if (alive) error.value = formatError(e) }
  finally { if (alive) pending.value.delete(task.task_id) }
}

async function showReason(task: TaskSummary) {
  if (pending.value.has(task.task_id)) return
  if (details.value[task.task_id]) { delete details.value[task.task_id]; return }
  pending.value.add(task.task_id)
  try {
    const state = await fetchTask(task.task_id)
    if (alive) details.value[task.task_id] = state.error || taskLabels[state.status] || '暂无详细记录'
  } catch (e) { if (alive) details.value[task.task_id] = formatError(e) }
  finally { if (alive) pending.value.delete(task.task_id) }
}

function time(value: number) {
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value * 1000))
}

onMounted(() => void refresh(true))
onBeforeUnmount(() => { alive = false; generation++; clearTimeout(timer) })
</script>

<template>
  <section class="task-section" aria-labelledby="task-heading">
    <header><div><h3 id="task-heading">后台计算</h3><p>仅显示你的最近 20 个任务；页面可见时每 5 秒更新。</p></div><button class="sm" :disabled="loading" @click="refresh(true)">{{ loading ? '正在更新…' : '刷新' }}</button></header>
    <p class="scope-note">{{ taskStorageNote(storage) }}</p>
    <p v-if="error" class="task-error" role="alert">{{ error }}<span v-if="tasks.length">下列为上次读取的记录。</span></p>
    <p v-if="!tasks.length" class="empty">{{ loading ? '正在读取任务…' : error ? '暂时无法读取任务' : '暂无后台任务' }}</p>
    <ol v-else class="task-list">
      <li v-for="task in tasks" :key="task.task_id">
        <div class="task-main"><strong>{{ task.description || '计算任务' }}</strong><span>{{ time(task.created_at) }} · 上海时间 · {{ taskElapsed(task.elapsed) }}</span><p v-if="taskContextNote(task)" class="task-context">{{ taskContextNote(task) }}</p></div>
        <span class="task-status" :class="{ active: ['pending', 'running', 'cancelling'].includes(task.status), failed: isTaskFailure(task.status) }">{{ taskStatusLabel(task) }}</span>
        <div class="task-action"><button v-if="task.status === 'pending' || task.status === 'running'" class="sm" :disabled="pending.has(task.task_id)" :aria-label="`取消 ${task.description || '计算任务'}`" @click="stop(task)">{{ pending.has(task.task_id) ? '正在请求…' : '取消任务' }}</button><button v-else-if="isTaskFailure(task.status)" class="sm" :disabled="pending.has(task.task_id)" :aria-expanded="!!details[task.task_id]" @click="showReason(task)">{{ details[task.task_id] ? '收起原因' : '查看原因' }}</button></div>
        <p v-if="details[task.task_id]" class="task-detail">{{ details[task.task_id] }}</p>
        <div v-if="task.storage === 'persistent' && isTaskTerminal(task.status)" class="task-retention">
          <template v-if="deleting === task.task_id"><span>删除此任务的输入和结果，不影响已保存策略；删除后无法恢复。</span><button class="sm" :disabled="pending.has(task.task_id)" @click="remove(task)">确认删除</button><button class="sm" :disabled="pending.has(task.task_id)" @click="deleting = null">保留</button></template>
          <button v-else class="text-action" :aria-label="`删除任务记录 ${task.description || ''}`" @click="deleting = task.task_id">删除记录</button>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.task-section{margin-top:28px;padding-top:24px;border-top:1px solid var(--border)}
header{display:flex;align-items:center;justify-content:space-between;gap:16px}h3{font-size:15px;font-weight:600}header p,.scope-note,.empty{font-size:12px;color:var(--text-muted);line-height:1.7}header p{margin:5px 0 0}.scope-note{margin:14px 0}.empty{padding:24px 0}
.task-list{list-style:none;margin:0;padding:0}.task-list li{display:grid;grid-template-columns:minmax(0,1fr) 80px 100px;gap:12px;align-items:center;padding:15px 0;border-top:1px solid var(--border)}.task-main{min-width:0}.task-main strong{display:block;font-size:13px;font-weight:500;overflow-wrap:anywhere;line-height:1.6}.task-main>span{display:block;margin-top:4px;font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums}.task-status{font-size:12px;color:var(--text-muted);text-align:right}.task-status.active{color:var(--accent,#65afff)}.task-status.failed{color:var(--text-muted)}.task-action{display:flex;justify-content:flex-end}.task-detail{grid-column:1/-1;margin:0;padding:8px 12px;background:rgba(255,255,255,.025);color:var(--text-muted);font-size:12px;line-height:1.7;overflow-wrap:anywhere;white-space:pre-wrap}.task-error{font-size:12px;line-height:1.7;color:#ffaaa4}.task-error span{display:block}.sm{white-space:nowrap;transition:background-color .15s ease}
.task-context{margin:6px 0 0;color:var(--text-muted);font-size:12px;line-height:1.7;overflow-wrap:anywhere}.task-status{white-space:nowrap}.task-retention{grid-column:1/-1;display:flex;justify-content:flex-end;align-items:center;flex-wrap:wrap;gap:8px}.task-retention>span{flex:1 0 100%;color:var(--text-muted);font-size:12px;line-height:1.6}.text-action{padding:2px 0;background:none;border:0;color:var(--text-muted);font-size:11px;box-shadow:none;min-height:24px}.text-action:hover{color:var(--text)}.task-retention .sm{min-height:32px}
@media(max-width:600px){.task-list li{grid-template-columns:minmax(0,1fr) auto;gap:10px}.task-main{grid-column:1/-1}.task-status{text-align:left}.task-action button{min-height:36px}header{align-items:flex-start}}
@media(prefers-reduced-motion:reduce){.sm{transition:none}}
</style>
