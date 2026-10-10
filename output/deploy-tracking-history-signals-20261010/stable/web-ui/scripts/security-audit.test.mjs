import { test } from 'node:test'
import assert from 'node:assert/strict'
import { auditDescription, auditTime, auditActions } from '../src/security-audit.ts'
import { fetchAuditRecords, logoutAllDevices } from '../src/api.ts'

test('audit description translates permissions and never renders arbitrary detail fields', () => {
  const item = { action:'update_user',target_name:'Alice',details:{role_before:'admin',role_after:'user',active_before:true,active_after:false,password:'secret'} }
  assert.equal(auditDescription(item), 'Alice · 管理员 → 标准用户 · 停用账户')
  assert.equal(auditDescription({action:'unknown',details:{password:'secret'}}),'—')
  assert.equal(auditDescription({action:'server_test',details:{node_count:10,reachable_count:7}}),'10 个节点 · 7 个可连接')
  assert.equal(auditActions.logout_all,'退出全部设备')
  assert.equal(auditActions.task_cancel,'请求取消任务')
  assert.equal(auditActions.task_delete,'删除任务记录')
  assert.equal(auditDescription({action:'task_delete',details:{task_id:'job-456',payload:'private'}}),'任务 job-456')
  assert.equal(auditDescription({action:'task_cancel',details:{task_id:'job-123'}}),'任务 job-123')
})

test('audit time is explicitly Shanghai time and invalid data remains readable', () => {
  assert.equal(auditTime('invalid'),'时间未记录')
  assert.match(auditTime('2026-10-09T01:00:00Z'), /09:00:00/)
})

test('audit API preserves bounded pagination/filter state and authenticated credentials', async t => {
  let seen
  t.mock.method(globalThis,'fetch',async (url,init) => {
    seen = {url:String(url),init}
    return new Response(JSON.stringify({items:[],next_cursor:null,retention_limit:10000}))
  })
  await fetchAuditRecords({before:15,action:'login',outcome:'denied',limit:50})
  assert.equal(seen.url,'/api/v1/admin/audit?before=15&action=login&outcome=denied&limit=50')
  assert.equal(seen.init.credentials,'same-origin')
  await logoutAllDevices()
  assert.equal(seen.url,'/api/v1/auth/logout-all')
  assert.equal(seen.init.method,'POST')
})
