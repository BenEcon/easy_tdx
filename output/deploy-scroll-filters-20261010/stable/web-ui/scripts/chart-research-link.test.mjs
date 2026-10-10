import test from 'node:test'
import assert from 'node:assert/strict'
import { barWindow, overlappingBars, nearestMarkers, timeLinkGraphic } from '../src/chart-research-link.ts'
import { ResearchRequestCache } from '../src/research-request-cache.ts'
const bar = (start, end) => ({ datetime: start, period_end: end })
test('single-bar time link is a thin line limited to each actual plot', () => {
  for (const rect of [{x:58,y:50,width:500,height:342},{x:58,y:420,width:500,height:115}]) {
    const item = timeLinkGraphic(rect,100,100,1,4)
    assert.equal(item.type,'line'); assert.equal(item.style.lineWidth,1)
    assert.deepEqual(item.shape,{x1:100,x2:100,y1:rect.y,y2:rect.y+rect.height})
    assert.equal(item.silent,true)
    assert.equal(timeLinkGraphic(rect,20,20,1,4),null)
    assert.equal(timeLinkGraphic(rect,600,600,1,4),null)
  }
})
test('multi-bar time link has no border and clips to plot, never clamps offscreen data to an edge', () => {
  const rect={x:58,y:50,width:500,height:342}
  const item=timeLinkGraphic(rect,40,100,4,5)
  assert.equal(item.type,'rect'); assert.equal(item.style.stroke,undefined);assert.equal(item.style.lineWidth,0)
  assert.deepEqual(item.shape,{x:58,y:50,width:47,height:342})
  assert.equal(timeLinkGraphic(rect,0,40,3,5),null)
  assert.equal(timeLinkGraphic(rect,600,640,3,5),null)
  assert.equal(timeLinkGraphic(rect,NaN,100,3,5),null)
  assert.equal(timeLinkGraphic({...rect,width:0},80,100,3,5),null)
})
test('time links map daily coverage to all minute bars, not a matching ordinal', () => {
  const rows = [bar('2026-09-10 10:00:00','2026-09-10 10:30:00'),bar('2026-09-10 10:30:00','2026-09-10 11:00:00'),bar('2026-09-11 10:00:00','2026-09-11 10:30:00')]
  assert.deepEqual(overlappingBars(rows,barWindow(bar('2026-09-10T00:00:00','2026-09-10 15:00:00'))),[0,1])
  assert.deepEqual(overlappingBars(rows,barWindow(rows[0])),[0])
  assert.deepEqual(overlappingBars(rows,{start:'2025-01-01 00:00:00',end:'2025-01-01 15:00:00'}),[])
})
test('weekly and monthly end-labelled bars cover earlier constituent dates without changing data', () => {
  const weekly = bar('2026-09-11 00:00:00','2026-09-11 15:00:00')
  assert.equal(barWindow(weekly,'WEEK').start,'2026-09-07 00:00:00')
  assert.equal(barWindow(weekly,'MONTH').start,'2026-09-01 00:00:00')
  assert.deepEqual(overlappingBars([weekly],{start:'2026-09-08 10:00:00',end:'2026-09-08 10:30:00'},'WEEK'),[0])
  assert.equal(weekly.datetime,'2026-09-11 00:00:00')
})
test('nearest marker wins regardless of signal family, only co-located points share chooser', () => {
  const points=[{value:'buy',center:[10,20],size:[10,10]},{value:'divergence',center:[15,20],size:[10,10]},{value:'history',center:[15,21],size:[10,10]}]
  assert.deepEqual(nearestMarkers(points,15,20),['divergence','history'])
  assert.deepEqual(nearestMarkers(points,10,20),['buy'])
  assert.deepEqual(nearestMarkers(points,100,100),[])
  assert.deepEqual(nearestMarkers([{value:'bad',center:[NaN,0],size:[10,10]}],0,0),[])
})
test('immutable request cache deduplicates pending work, isolates payload keys and retries errors', async () => {
  const cache = new ResearchRequestCache(2);let calls=0
  const load=async()=>++calls
  const [a,b]=await Promise.all([cache.get('same',load),cache.get('same',load)])
  assert.equal(a,b);assert.equal(calls,1)
  await cache.get('changed-window',load);await cache.get('changed-rules',load)
  await cache.get('same',load);assert.equal(calls,4)
  await assert.rejects(cache.get('fail',async()=>{throw Error('abort')}))
  assert.equal(await cache.get('fail',async()=>42),42)
  cache.clear();assert.equal(await cache.get('same',load),5)
})
