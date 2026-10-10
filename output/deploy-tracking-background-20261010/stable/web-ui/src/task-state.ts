import type { TaskListResponse } from './types'

export const taskLabels: Record<string, string> = {
  pending: '排队中', running: '计算中', cancelling: '正在取消',
  done: '已完成', failed: '失败', cancelled: '已取消', timed_out: '计算超时',
}

/** Reject broken responses before replacing the last usable task list. */
export function validateTaskList(value: unknown): TaskListResponse {
  const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
  const storage = (v: unknown) => v === undefined || v === 'memory' || v === 'persistent'
  const nonnegative = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0
  const invalid = () => { throw new Error('任务列表响应格式异常，未采用该结果；请稍后刷新') }
  if (!object(value) || !Array.isArray(value.tasks) || value.count !== value.tasks.length || !storage(value.storage)) return invalid()
  const ids = new Set<string>()
  for (const task of value.tasks) {
    if (!object(task) || typeof task.task_id !== 'string' || !task.task_id.trim() || ids.has(task.task_id)
      || typeof task.status !== 'string' || !Object.hasOwn(taskLabels, task.status)
      || typeof task.description !== 'string' || !nonnegative(task.created_at) || task.created_at > 8.64e12
      || !nonnegative(task.elapsed) || !storage(task.storage)) return invalid()
    ids.add(task.task_id)
  }
  return value as unknown as TaskListResponse
}

export function isTaskFailure(status: string): boolean {
  return ['failed', 'cancelled', 'timed_out'].includes(status)
}

export function isTaskTerminal(status: string): boolean {
  return status === 'done' || isTaskFailure(status)
}

export function taskFailureMessage(state: {status: string; error?: string | null}): string {
  return state.error || taskLabels[state.status] || '任务状态未知'
}

export function taskElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  return seconds < 60 ? `${Math.floor(seconds)} 秒` : `${Math.floor(seconds / 60)} 分 ${Math.floor(seconds % 60)} 秒`
}

type TaskInfo = {
  status: string
  execution_compatible?: boolean | null
  recovery_count?: number
  checkpoint_grid_points?: number
  resumed_grid_points?: number
  checkpoint_scan_targets?: number
  resumed_scan_targets?: number
  checkpoint_signal_bars?: number
  resumed_signal_bars?: number
  checkpoint_order_signals?: number
  resumed_order_signals?: number
  checkpoint_pnl_trades?: number
  resumed_pnl_trades?: number
  checkpoint_equity_bars?: number
  resumed_equity_bars?: number
  last_recovery_reason?: string | null
}

export function taskStatusLabel(task: TaskInfo): string {
  if (task.status === 'pending' && task.execution_compatible === false) return '等待匹配版本'
  return taskLabels[task.status] || task.status
}

export function taskContextNote(task: TaskInfo): string {
  const notes: string[] = []
  if (task.execution_compatible === false) {
    notes.push(task.status === 'pending'
      ? '输入属于其他执行版本，不会套用当前规则重算；可等待匹配服务或取消后重新提交。'
      : '此记录属于其他执行版本，原始结果保留，不会改写为当前规则。')
  }
  if (Number.isInteger(task.recovery_count) && (task.recovery_count ?? 0) > 0) {
    const reason = task.last_recovery_reason === 'supervisor_lost' ? '服务异常退出后' : '服务重新启动后'
    notes.push(`${reason}重新排队 ${task.recovery_count} 次。保持原冻结输入；支持检查点的计算会先核验后续算，其余从头计算。`)
  }
  if (Number.isInteger(task.resumed_grid_points) && (task.resumed_grid_points ?? 0) > 0) {
    notes.push(`本次执行已从检查点复用 ${task.resumed_grid_points} 个已处理参数组合，包含无效或失败组合的原记录。`)
  } else if (Number.isInteger(task.checkpoint_grid_points) && (task.checkpoint_grid_points ?? 0) > 0) {
    notes.push(`已保存 ${task.checkpoint_grid_points} 个参数组合的检查点，不代表全部计算完成。`)
  }
  if (Number.isInteger(task.resumed_signal_bars) && (task.resumed_signal_bars ?? 0) > 0) {
    notes.push(`本次执行已复用 ${task.resumed_signal_bars} 根信号生成状态；其他阶段单独核验，不代表回测完成。`)
  } else if (Number.isInteger(task.checkpoint_signal_bars) && (task.checkpoint_signal_bars ?? 0) > 0) {
    notes.push(`已保存 ${task.checkpoint_signal_bars} 根信号生成状态；按策略槽位累计，不代表回测完成。`)
  }
  const phases = [
    ['撮合信号', task.checkpoint_order_signals, task.resumed_order_signals],
    ['成本记录', task.checkpoint_pnl_trades, task.resumed_pnl_trades],
    ['权益柱', task.checkpoint_equity_bars, task.resumed_equity_bars],
  ] as const
  const phaseNotes = phases.flatMap(([label, saved, reused]) => {
    if (Number.isInteger(reused) && (reused ?? 0) > 0) return [`${label}已复用 ${reused}`]
    if (Number.isInteger(saved) && (saved ?? 0) > 0) return [`${label}已保存 ${saved}`]
    return []
  })
  if (phaseNotes.length) notes.push(`${phaseNotes.join(' · ')}；按槽位累计，不代表全部结果已完成。`)
  if (Number.isInteger(task.resumed_scan_targets) && (task.resumed_scan_targets ?? 0) > 0) {
    notes.push(`本次执行已复用 ${task.resumed_scan_targets} 个已完成扫描条目，保留原错误行及数据来源。`)
  } else if (Number.isInteger(task.checkpoint_scan_targets) && (task.checkpoint_scan_targets ?? 0) > 0) {
    notes.push(`已保存 ${task.checkpoint_scan_targets} 个扫描条目的检查点，不代表整批扫描完成。`)
  }
  return notes.join(' ')
}

export function taskStorageNote(storage?: string): string {
  if (storage === 'persistent') return '记录已持久保存，刷新或重启网页服务后仍可查询。排队任务等待匹配版本的计算服务。'
  if (storage === 'memory') return '当前使用临时内存记录，服务重启后不保留。'
  return '仅显示当前账户的任务。取消中的任务会等待实际计算退出。'
}
