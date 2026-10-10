import test from 'node:test'
import assert from 'node:assert/strict'
import { ChartViewportMemory, readZoom } from '../src/chart-viewport.ts'

test('rejects invalid saved zooms', () => {
  for (const value of [null, {}, {start:-1,end:30}, {start:50,end:20},
    {start:0,end:101}, {start:NaN,end:30}, {start:'0',end:30}]) assert.equal(readZoom(value), null)
  assert.deepEqual(readZoom({start:0,end:100}), {start:0,end:100})
})
test('same-snapshot redraw keeps current manually chosen view', () => {
  const memory = new ChartViewportMemory(), scope = {}
  assert.equal(memory.update(scope, null, {start:0,end:100}), null)
  assert.deepEqual(memory.update(scope, null, {start:20,end:35}), {start:20,end:35})
})
test('focus redraw keeps manual zoom; clearing restores pre-focus view', () => {
  const memory = new ChartViewportMemory(), scope = {}, focus = {}
  memory.update(scope, null, null)
  assert.equal(memory.update(scope, focus, {start:20,end:35}), null)
  assert.deepEqual(memory.update(scope, focus, {start:50,end:60}), {start:50,end:60})
  assert.deepEqual(memory.update(scope, null, {start:50,end:60}), {start:20,end:35})
})
test('switching focus preserves the original return view', () => {
  const memory = new ChartViewportMemory(), scope = {}
  memory.update(scope, null, null)
  memory.update(scope, {}, {start:10,end:40})
  assert.equal(memory.update(scope, {}, {start:70,end:80}), null)
  assert.deepEqual(memory.update(scope, null, {start:90,end:99}), {start:10,end:40})
})
test('new snapshot resets saved focus view and never revives old zoom', () => {
  const memory = new ChartViewportMemory(), scope = {}, next = {}, focus = {}
  memory.update(scope, null, null)
  memory.update(scope, focus, {start:10,end:40})
  assert.equal(memory.update(next, focus, {start:70,end:80}), null)
  assert.equal(memory.update(next, null, {start:70,end:80}), null)
})
