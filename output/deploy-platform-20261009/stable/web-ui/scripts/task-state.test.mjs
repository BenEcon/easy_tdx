import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isTaskTerminal, isTaskFailure, taskFailureMessage, taskElapsed, taskStatusLabel, taskContextNote, taskStorageNote } from '../src/task-state.ts'
import { runBacktestWithPolling, runSignalScanWithPolling, asSignalScanResult, cancelTask, deleteTask, formatError } from '../src/api.ts'

test('cancelling is not terminal and elapsed values remain readable', () => {
  for (const status of ['pending','running','cancelling']) assert.equal(isTaskTerminal(status),false)
  for (const status of ['done','failed','cancelled','timed_out']) assert.equal(isTaskTerminal(status),true)
  assert.equal(isTaskFailure('done'),false)
  assert.equal(taskFailureMessage({status:'cancelled'}),'已取消')
  assert.equal(taskFailureMessage({status:'timed_out',error:'计算超时原因'}),'计算超时原因')
  assert.equal(taskElapsed(65.9),'1 分 5 秒')
  assert.equal(taskElapsed(Infinity),'—')
})

for (const poll of [runBacktestWithPolling, runSignalScanWithPolling]) {
  for (const terminal of ['cancelled','timed_out']) {
    test(`${poll.name} waits through cancelling and returns ${terminal}`, async t => {
      const queue = [{task_id:'test',status:'pending'}, {task_id:'test',status:'cancelling'}, {task_id:'test',status:terminal,result:null}]
      t.mock.method(globalThis,'fetch',async () => new Response(JSON.stringify(queue.shift())))
      const seen = []
      const result = await poll({}, state => seen.push(state.status), 0, 1000)
      assert.deepEqual(seen,['cancelling',terminal])
      assert.equal(result.status,terminal)
      assert.equal(queue.length,0)
    })
  }
}

test('cancel API uses POST, and partial cancelled scan results are never accepted', async t => {
  let request
  t.mock.method(globalThis,'fetch',async (url, init) => { request={url,init}; return new Response(JSON.stringify({status:'cancelling'})) })
  await cancelTask('task/1')
  assert.equal(request.url,'/api/v1/backtest/tasks/task%2F1/cancel')
  assert.equal(request.init.method,'POST')
  assert.equal(request.init.credentials,'same-origin')
  assert.throws(() => asSignalScanResult({status:'cancelled',result:{rows:[]}}),/已取消/)
  assert.deepEqual(asSignalScanResult({status:'done',result:{rows:[]}}),{rows:[]})
})

test('persistent recovery and version mismatch are distinct from completion', () => {
  const pending = {status:'pending', execution_compatible:false, recovery_count:2, last_recovery_reason:'supervisor_lost'}
  assert.equal(taskStatusLabel(pending),'等待匹配版本')
  assert.equal(isTaskTerminal(pending.status),false)
  assert.match(taskContextNote(pending),/不会套用当前规则/)
  assert.match(taskContextNote(pending),/异常退出后.*重新排队 2 次.*先核验后续算.*其余从头计算/)
  assert.equal(taskStatusLabel({...pending,status:'done'}),'已完成')
  assert.match(taskContextNote({...pending,status:'done'}),/原始结果保留/)
  assert.equal(taskContextNote({status:'pending',execution_compatible:true,recovery_count:0}),'')
  assert.match(taskStorageNote('persistent'),/重启网页服务后仍可查询/)
  assert.match(taskStorageNote('memory'),/重启后不保留/)
  assert.doesNotMatch(taskStorageNote(),/持久保存/)
})

test('terminal task deletion handles empty 204 and encodes identity', async t => {
  let request
  t.mock.method(globalThis,'fetch',async (url,init) => {
    request={url,init}; return new Response(null,{status:204})
  })
  await deleteTask('task/1')
  assert.equal(request.url,'/api/v1/backtest/tasks/task%2F1')
  assert.equal(request.init.method,'DELETE')
  assert.equal(request.init.credentials,'same-origin')
})

test('checkpoint presence is not confused with verified reuse or task completion', () => {
  assert.match(taskContextNote({status:'running', checkpoint_grid_points:12}), /已保存 12.*不代表全部计算完成/)
  assert.doesNotMatch(taskContextNote({status:'running', checkpoint_grid_points:12}), /已从检查点复用/)
  const resumed = taskContextNote({status:'running', checkpoint_grid_points:15, resumed_grid_points:12})
  assert.match(resumed, /本次执行已从检查点复用 12.*无效或失败/)
  assert.doesNotMatch(resumed, /全部完成|100%/)
  assert.equal(taskContextNote({status:'running', resumed_grid_points:-1, checkpoint_grid_points:NaN}), '')
  assert.match(taskContextNote({status:'running', checkpoint_scan_targets:3}), /已保存 3 个扫描条目.*不代表整批扫描完成/)
  assert.match(taskContextNote({status:'done', resumed_scan_targets:2}), /已复用 2 个已完成扫描条目.*保留原错误行及数据来源/)
  assert.doesNotMatch(taskContextNote({status:'running', resumed_scan_targets:2}), /参数组合/)
  assert.match(taskContextNote({status:'running', checkpoint_signal_bars:128}), /已保存 128 根信号生成状态.*按策略槽位累计.*不代表回测完成/)
  assert.match(taskContextNote({status:'running', resumed_signal_bars:64}), /已复用 64 根信号生成状态.*其他阶段单独核验/)
  assert.doesNotMatch(taskContextNote({status:'running', resumed_signal_bars:64}), /已完成|100%/)
  assert.match(taskContextNote({status:'running', resumed_order_signals:64, checkpoint_pnl_trades:128, resumed_equity_bars:256}), /撮合信号已复用 64 · 成本记录已保存 128 · 权益柱已复用 256.*不代表全部结果已完成/)
  assert.equal(taskContextNote({status:'running', resumed_order_signals:-1, checkpoint_equity_bars:NaN}), '')
})

test('cached completed submission is retrieved rather than shown as running', async t => {
  const replies = [
    {task_id:'cached',status:'done',reused:true,storage:'persistent'},
    {task_id:'cached',status:'done',result:{metrics:{}}},
  ]
  t.mock.method(globalThis,'fetch',async () => new Response(JSON.stringify(replies.shift())))
  assert.equal((await runBacktestWithPolling({},undefined,0,1000)).status,'done')
  assert.equal(replies.length,0)
})

test('network failures are localized across WebKit, Chromium and Firefox', () => {
  for (const message of ['Load failed','Failed to fetch','NetworkError when attempting to fetch resource.']) {
    assert.match(formatError(new TypeError(message)),/网络错误.*稍后重试/)
  }
  assert.equal(formatError(new TypeError('invalid calculation input')),'invalid calculation input')
})
