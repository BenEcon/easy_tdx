import test from 'node:test'
import assert from 'node:assert/strict'
import { nextPenPreview, consolidationAppearance } from '../src/structure-preview.ts'

const bars = [
  {datetime:'2026-10-01 00:00:00',high:10,low:8},
  {datetime:'2026-10-02 00:00:00',high:9,low:7},
  {datetime:'2026-10-03 00:00:00',high:8,low:6},
  {datetime:'2026-10-04 00:00:00',high:9,low:7},
]
const pen = {index:0,direction:'up',start_date:'2026-09-01',end_date:bars[0].datetime,start_value:5,end_value:10,high:10,low:5,done:false}
test('reverse preview uses observed extreme, not last close or a future target',()=>{
  assert.deepEqual(nextPenPreview(bars,[pen]), {start:0,end:2,startPrice:10,endPrice:6,direction:'down'})
  assert.equal(pen.done,false)
  assert.equal(bars.length,4)
})
test('mirrored lows produce an upward reference',()=>{
  const inverted = bars.map(bar=>({...bar,high:20-bar.low,low:20-bar.high}))
  assert.deepEqual(nextPenPreview(inverted,[{...pen,direction:'down',end_value:10}]),{start:0,end:2,startPrice:10,endPrice:14,direction:'up'})
})
test('no invented reference for missing, ambiguous, extending, or invalid inputs',()=>{
  assert.equal(nextPenPreview(bars,[]),null)
  assert.equal(nextPenPreview(bars.slice(0,1),[pen]),null)
  assert.equal(nextPenPreview(bars,[{...pen,end_date:'missing'}]),null)
  assert.equal(nextPenPreview([bars[0],...bars],[pen]),null)
  assert.equal(nextPenPreview([...bars,{datetime:'later',high:11,low:5}],[pen]),null)
  assert.equal(nextPenPreview([bars[0],{...bars[1],high:NaN}],[pen]),null)
})
test('replay prefix cannot use a later extreme; ties retain first occurrence',()=>{
  assert.equal(nextPenPreview(bars.slice(0,2),[pen]).end,1)
  assert.equal(nextPenPreview([...bars,{datetime:'later',high:8,low:6}],[pen]).end,2)
  assert.equal(nextPenPreview(bars,[{...pen,end_date:pen.end_date.replace(' ','T')}]).end,2)
})
test('ongoing consolidation differs by color, line pattern, and fill',()=>{
  const complete=consolidationAppearance(true), ongoing=consolidationAppearance(false)
  assert.equal(complete.itemStyle.borderType,'solid')
  assert.equal(ongoing.itemStyle.borderType,'dashed')
  assert.notEqual(complete.itemStyle.borderColor,ongoing.itemStyle.borderColor)
  assert.notEqual(complete.label.color,ongoing.label.color)
})
