import test from 'node:test'
import assert from 'node:assert/strict'
import { studyWindowError, studyTime, studyStatus, studyNumber } from '../src/research-study.ts'
import { nextPenPreview } from '../src/structure-preview.ts'

test('window is exchange local and bounded by the snapshot cutoff', () => {
  assert.equal(studyTime('2026-10-08T15:00'), '2026-10-08 15:00:00')
  assert.equal(studyWindowError('range','2026-09-01T09:30','2026-10-08T15:00','2026-10-08 15:00:00'),'')
  assert.match(studyWindowError('range','','','2026-10-08 15:00:00'), /起止/)
  assert.match(studyWindowError('range','2026-10-09T15:00','2026-10-08T15:00','2026-10-08 15:00:00'), /开始/)
  assert.match(studyWindowError('range','2026-09-01T09:30','2026-10-09T15:00','2026-10-08 15:00:00'), /共同截止/)
})
test('missing numbers and candidate status are never promoted', () => {
  assert.equal(studyNumber(null),'不可计算')
  assert.equal(studyStatus('candidate'),'候选')
  assert.equal(studyStatus('superseded'),'失效 / 被替代')
})
test('amber projection resolves daily and minute labels, ignores open candle', () => {
  const bars = [{datetime:'2026-10-01 00:00:00',high:12,low:10}, {datetime:'2026-10-02 00:00:00',high:11,low:9}, {datetime:'2026-10-03 00:00:00',high:20,low:8,is_closed:false}]
  const pen = {direction:'up',end_date:'2026-10-01',end_value:12}
  assert.equal(nextPenPreview(bars,[pen]).end,1)
  bars[2].is_closed=true
  assert.equal(nextPenPreview(bars,[pen]),null)
  const minutes=bars.slice(0,2).map((b,i)=>({...b,datetime:`2026-10-01 10:${i?'30':'00'}:00`}))
  assert.equal(nextPenPreview(minutes,[{...pen,end_date:'2026-10-01 10:00'}]).end,1)
})
