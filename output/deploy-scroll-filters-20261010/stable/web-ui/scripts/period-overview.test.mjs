import test from 'node:test'
import assert from 'node:assert/strict'
import { overviewPeriods, overviewColumns, periodOverviewCells } from '../src/period-overview.ts'

const row = () => ({ price: 10.1234, volume_ratio: 0, axis: '零轴下方', histogram: '绿柱 · 缩短',
  pairs: { ma: { fast: 10, slow: 11, description: '快线仍在慢线下方' },
    volume: { fast: 0, slow: null, description: '样本不足' },
    macd: { fast: -0.001, slow: -0.002, description: 'DIF 高于 DEA' } },
  ma_research: { bull: { to: null }, bear: { to: 20 } },
  direction_observation: { strict: { direction: 'down', locked: false, start_date: '2026-09-01', end_date: '2026-09-11', start_price: 12, end_price: 10 },
    description: '底分型后向上观察，尚未反向成笔', known_date: '2026-09-14' },
  divergences: [{ kind: 'macd', date: '2026-09-11', direction: 'down', status: 'candidate', confirmed_date: null }],
  observations: [], warmup_warning: false, excluded_bars: 0,
  window: { start: '2026-08-01', end: '2026-09-14', count: 20, truncated: false },
})
test('matrix defaults to five requested periods and includes separate buy/sell evidence column', () => {
  assert.deepEqual(overviewPeriods, ['WEEK', 'DAY', 'MIN_30', 'MIN_15', 'MIN_5'])
  assert.equal(overviewColumns.length, 7)
  assert.equal(periodOverviewCells(row()).length, 7)
  assert.equal(overviewColumns[5], '买卖点')
})
test('does not turn current reversal observation into a confirmed opposite pen', () => {
  const cells = periodOverviewCells(row())
  assert.match(cells[3][0], /向下严格笔.*末端可延伸/)
  assert.match(cells[3][2], /尚未反向成笔/)
  assert.match(cells[4][0], /双线底背离 · 候选/)
  assert.doesNotMatch(cells[4][0], /确认 /)
})
test('keeps true zero distinct from missing, and numerical display never overwrites original axis judgment', () => {
  const input = row(), before = JSON.stringify(input)
  const cells = periodOverviewCells(input)
  assert.equal(cells[0][0], '收盘 10.12')
  assert.equal(cells[1][0], 'MAVOL5 0.00')
  assert.equal(cells[1][1], 'MAVOL10 不可计算')
  assert.match(cells[1][3], /0.00 倍/)
  assert.match(cells[2][1], /零轴下方/)
  assert.equal(JSON.stringify(input), before)
})
test('keeps divergence family, extrema and actual confirmation separate; never drops records', () => {
  const input = row()
  input.divergences.push({ kind: 'macd_wave', date: '2026-09-12', direction: 'up', status: 'confirmed', confirmed_date: '2026-09-18' })
  const cells = periodOverviewCells(input)
  assert.match(cells[4][0], /标准波段顶背离 · 已确认；极值 2026-09-12；确认 2026-09-18/)
  assert.equal(cells[4].length, 2)
  assert.equal(input.divergences[0].date, '2026-09-11')
})
test('missing pen and divergence are bounded claims; quality limitations stay visible', () => {
  const input = row()
  input.direction_observation.strict = null
  input.divergences = []
  input.warmup_warning = true
  input.window.truncated = true
  input.excluded_bars = 3
  const cells = periodOverviewCells(input)
  assert.equal(cells[3][0], '尚无严格笔')
  assert.match(cells[4][0], /本研究窗口.*不代表历史/)
  assert.match(cells[6].join(' '), /预热不足.*覆盖不足.*排除 3 根/)
})
test('buy/sell evidence distinguishes missing old archives, no points, structure and M1',()=>{
  const input=row()
  assert.match(periodOverviewCells(input)[5][0],/未记录.*不能视为没有/)
  input.buy_sell_points=[]
  assert.match(periodOverviewCells(input)[5][0],/无已确认/)
  input.buy_sell_points=[{type:'2buy',family:'structure',side:'buy',status:'confirmed',date:'2026-09-01',confirmed_date:'2026-09-05',known_at:'2026-09-05 15:00:00',price:10.129,reason:'弱势回试',source:'confirmed_segment_base_v1',evidence:{}}, {type:'M1',family:'macd',side:'sell',status:'confirmed',date:'2026-09-03',confirmed_date:'2026-09-06',price:12,reason:'标准波段'}]
  const cells=periodOverviewCells(input)[5]
  assert.match(cells[0],/结构二买.*极值 2026-09-01 · 10.13；确认 2026-09-05 15:00:00.*弱势回试/)
  assert.match(cells[1],/M1 · MACD 卖出提示（非结构一类点）/)
})
