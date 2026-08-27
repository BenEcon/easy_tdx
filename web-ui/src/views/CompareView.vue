<script setup lang="ts">
// 结果对比页面：选 2-4 个已完成的回测 task，叠加净值曲线 + 横向指标对比。
// 支持单标的回测（equity_curve）和组合回测（combined_equity）的混合对比。

import { onMounted, ref, watch } from 'vue'

import ChartFrame from '../components/ChartFrame.vue'
import CompareChart from '../components/CompareChart.vue'
import CompareTable from '../components/CompareTable.vue'
import { fetchTask, fetchTaskList, formatError } from '../api'
import type { BacktestResult, EquityPoint, TaskSummary } from '../types'

/** 统一的可对比项：无论单标的还是组合，都归一化为 equity + performance。 */
interface CompareItem {
  label: string
  equity: EquityPoint[]
  performance: Record<string, number>
}

const taskList = ref<TaskSummary[]>([])
const loading = ref(false)
const error = ref('')
const selectedIds = ref<Set<string>>(new Set())
const details = ref<Map<string, CompareItem>>(new Map())

onMounted(loadTasks)

async function loadTasks() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchTaskList(20)
    taskList.value = resp.tasks.filter((t) => t.status === 'done')
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

/** 从 task result 提取可对比的 equity + performance。
 * 支持单标的（equity_curve/performance）和组合（combined_equity/total_performance）。 */
function extractComparable(
  result: Record<string, unknown> | null,
): { equity: EquityPoint[]; performance: Record<string, number> } | null {
  if (!result) return null
  // 单标的回测
  if (result.performance && result.equity_curve) {
    return {
      equity: result.equity_curve as EquityPoint[],
      performance: result.performance as Record<string, number>,
    }
  }
  // 组合回测
  if (result.total_performance && result.combined_equity) {
    return {
      equity: result.combined_equity as EquityPoint[],
      performance: result.total_performance as Record<string, number>,
    }
  }
  return null
}

async function toggle(taskId: string) {
  if (selectedIds.value.has(taskId)) {
    selectedIds.value.delete(taskId)
    details.value.delete(taskId)
  } else {
    if (selectedIds.value.size >= 4) return
    selectedIds.value.add(taskId)
    try {
      const state = await fetchTask(taskId)
      const comparable = extractComparable(state.result as Record<string, unknown> | null)
      if (!comparable) {
        throw new Error('该任务结果不含净值曲线（寻优任务等不可对比）')
      }
      details.value.set(taskId, { label: state.description, ...comparable })
    } catch (e) {
      selectedIds.value.delete(taskId)
      error.value = e instanceof Error ? e.message : String(e)
    }
  }
  selectedIds.value = new Set(selectedIds.value)
  details.value = new Map(details.value)
}

const compareItems = ref<Array<{ label: string; result: BacktestResult }>>([])
function refreshItems() {
  // CompareChart/CompareTable 期望 { label, result: BacktestResult }，
  // 这里把归一化的 equity/performance 包装回去
  compareItems.value = Array.from(details.value.values()).map((item) => ({
    label: item.label,
    result: { equity_curve: item.equity, performance: item.performance } as unknown as BacktestResult,
  }))
}

watch(details, refreshItems, { deep: true })
</script>

<template>
  <div class="compare-view">
    <aside class="config-panel">
      <section class="panel-section">
        <h3>选择对比任务</h3>
        <button class="refresh-btn" :disabled="loading" @click="loadTasks">
          {{ loading ? '加载中…' : '刷新列表' }}
        </button>
        <p class="hint">勾选 2-4 个已完成的回测任务进行对比：</p>
        <div v-if="taskList.length === 0" class="empty">暂无已完成的任务</div>
        <div v-for="t in taskList" :key="t.task_id" class="task-item">
          <label class="check">
            <input
              type="checkbox"
              :checked="selectedIds.has(t.task_id)"
              :disabled="!selectedIds.has(t.task_id) && selectedIds.size >= 4"
              @change="toggle(t.task_id)"
            />
            <span class="task-desc">{{ t.description || t.task_id.slice(0, 8) }}</span>
          </label>
          <span class="task-meta">{{ t.elapsed.toFixed(1) }}s</span>
        </div>
      </section>
    </aside>

    <main class="report-panel">
      <div v-if="error" class="error-banner">⚠ {{ error }}</div>

      <div v-if="compareItems.length < 2" class="placeholder">
        <p>勾选至少 2 个任务进行对比</p>
      </div>

      <div v-else class="report-content">
        <section class="report-section">
          <ChartFrame title="净值曲线对比（归一化）" description="全屏辨识不同任务的收益路径差异">
            <CompareChart :items="compareItems" />
          </ChartFrame>
        </section>

        <section class="report-section">
          <h3>指标对比</h3>
          <CompareTable :items="compareItems" />
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.compare-view {
  display: flex;
  height: 100%;
}
.config-panel {
  width: 320px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  padding: 16px;
  overflow-y: auto;
}
.panel-section h3 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
}
.refresh-btn {
  width: 100%;
  margin-bottom: 12px;
}
.hint {
  color: var(--text-muted);
  font-size: 12px;
  margin-bottom: 10px;
}
.empty {
  color: var(--text-dim);
  font-size: 13px;
  padding: 16px 0;
}
.task-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.check input[type='checkbox'] {
  width: auto;
}
.task-desc {
  color: var(--text);
  font-family: var(--font-mono);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.task-meta {
  color: var(--text-dim);
  font-size: 11px;
  flex-shrink: 0;
}
.report-panel {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-dim);
}
.error-banner {
  background: rgba(239, 65, 70, 0.12);
  border: 1px solid var(--up);
  color: var(--up);
  padding: 10px 14px;
  border-radius: var(--radius);
  margin-bottom: 16px;
  font-size: 13px;
}
.report-section {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 16px;
}
.report-section h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 12px;
}
</style>
