export interface AuditRecord {
  id: number
  occurred_at: string
  action: string
  actor_id: string | null
  actor_name: string | null
  target_id: string | null
  target_name: string | null
  outcome: 'success' | 'denied' | 'failed'
  details: Record<string, unknown>
}

export interface AuditPage {
  items: AuditRecord[]
  next_cursor: number | null
  retention_limit: number
}

export const auditActions: Record<string, string> = {
  setup: '初始化账户', create_user: '创建账户', update_user: '修改权限或状态',
  set_password: '修改或重置密码', login: '登录', logout: '退出登录',
  logout_all: '退出全部设备', server_test: '节点测速', server_switch: '切换节点',
  task_cancel: '请求取消任务', task_delete: '删除任务记录',
}

export const auditOutcomes = { success: '成功', denied: '未通过', failed: '失败' }

export function auditTime(value: string): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date)
}

export function auditDescription(item: AuditRecord): string {
  const detail = item.details ?? {}
  const parts: string[] = []
  if (item.target_name) parts.push(item.target_name)
  if (item.action === 'update_user') {
    const roles: Record<string, string> = { admin: '管理员', user: '标准用户' }
    if (detail.role_before !== detail.role_after) {
      parts.push(`${roles[String(detail.role_before)] ?? '未知角色'} → ${roles[String(detail.role_after)] ?? '未知角色'}`)
    }
    if (detail.active_before !== detail.active_after) parts.push(detail.active_after ? '启用账户' : '停用账户')
    if (parts.length === 1) parts.push('设置未变化')
  } else if (item.action === 'server_test') {
    if (typeof detail.node_count === 'number') parts.push(`${detail.node_count} 个节点`)
    if (typeof detail.reachable_count === 'number') parts.push(`${detail.reachable_count} 个可连接`)
  } else if (item.action === 'server_switch') {
    if (typeof detail.node_before === 'string' && typeof detail.node_after === 'string') {
      parts.push(`${detail.node_before} → ${detail.node_after}`)
    }
  } else if (['task_cancel', 'task_delete'].includes(item.action) && typeof detail.task_id === 'string') {
    parts.push(`任务 ${detail.task_id}`)
  }
  return parts.join(' · ') || '—'
}
