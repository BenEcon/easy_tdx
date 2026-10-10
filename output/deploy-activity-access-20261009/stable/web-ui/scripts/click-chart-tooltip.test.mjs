import test from 'node:test'
import assert from 'node:assert/strict'
import { clickTooltipOptions, installClickChartTooltip } from '../src/click-chart-tooltip.ts'

function fixture() {
  const listeners = new Map(), rendererListeners = new Map(), chartListeners = new Map(), actions = []
  const document = {
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: (type, fn) => { assert.equal(listeners.get(type), fn); listeners.delete(type) },
  }
  const renderer = {
    on: (type, fn) => rendererListeners.set(type, fn),
    off: (type, fn) => { assert.equal(rendererListeners.get(type), fn); rendererListeners.delete(type) },
  }
  const chart = {
    getZr: () => renderer, dispatchAction: action => actions.push(action),
    on: (type, fn) => chartListeners.set(type, fn),
    off: (type, fn) => { assert.equal(chartListeners.get(type), fn); chartListeners.delete(type) },
  }
  const container = { ownerDocument: document }
  return { container, chart, listeners, rendererListeners, chartListeners, actions }
}

test('default inactive; moving does not show cards and leaving does not deactivate', () => {
  const f = fixture()
  installClickChartTooltip(f.chart, f.container)
  assert.equal(clickTooltipOptions.triggerOn, 'none')
  assert.equal(clickTooltipOptions.hideDelay, 0)
  assert.deepEqual(f.actions, [])
  f.rendererListeners.get('mousemove')({offsetX:120,offsetY:90})
  assert.deepEqual(f.actions, [])
  assert.deepEqual([...f.rendererListeners.keys()], ['click', 'mousemove'])
})

test('object previews can read date-card activation without activating it', () => {
  const f = fixture()
  const controller = installClickChartTooltip(f.chart, f.container)
  assert.equal(controller.isActive(), false)
  assert.deepEqual(f.actions, [])
  f.rendererListeners.get('click')({offsetX:100,offsetY:80})
  assert.equal(controller.isActive(), true)
  f.chartListeners.get('datazoom')()
  assert.equal(controller.isActive(), true)
  f.listeners.get('click')({composedPath:()=>[]})
  assert.equal(controller.isActive(), false)
  controller.dispose()
  assert.equal(controller.isActive(), false)
})

test('click selects a point; outside click closes; inside click is not dismissed', () => {
  const f = fixture()
  installClickChartTooltip(f.chart, f.container)
  f.rendererListeners.get('click')({ offsetX: 100, offsetY: 80 })
  assert.deepEqual(f.actions.at(-1), {type:'showTip', x:100, y:80})
  f.actions.length = 0
  f.listeners.get('click')({composedPath: () => [f.container]})
  assert.deepEqual(f.actions, [])
  f.listeners.get('click')({composedPath: () => []})
  assert.deepEqual(f.actions, [{type:'updateAxisPointer',currTrigger:'leave'}, {type:'hideTip'}])
  f.actions.length = 0
  f.rendererListeners.get('mousemove')({offsetX:180,offsetY:90})
  assert.deepEqual(f.actions, [])
})

test('activated cards follow movement until outside dismissal, then require another click', () => {
  const f = fixture()
  installClickChartTooltip(f.chart, f.container)
  f.rendererListeners.get('click')({offsetX:100,offsetY:80})
  f.actions.length = 0
  f.rendererListeners.get('mousemove')({offsetX:160,offsetY:90})
  f.rendererListeners.get('mousemove')({offsetX:220,offsetY:95})
  assert.deepEqual(f.actions, [{type:'showTip',x:160,y:90},{type:'showTip',x:220,y:95}])
  f.listeners.get('click')({composedPath: () => []})
  f.actions.length = 0
  f.rendererListeners.get('mousemove')({offsetX:280,offsetY:80})
  assert.deepEqual(f.actions, [])
  f.rendererListeners.get('click')({offsetX:280,offsetY:80})
  f.rendererListeners.get('mousemove')({offsetX:300,offsetY:90})
  assert.deepEqual(f.actions.at(-1), {type:'showTip',x:300,y:90})
})

test('zoom clears stale coordinates but preserves activation', () => {
  const f = fixture()
  installClickChartTooltip(f.chart, f.container)
  f.rendererListeners.get('click')({offsetX:100,offsetY:80})
  f.chartListeners.get('datazoom')()
  assert.equal(f.actions.at(-1).type,'hideTip')
  f.rendererListeners.get('mousemove')({offsetX:200,offsetY:80})
  assert.deepEqual(f.actions.at(-1),{type:'showTip',x:200,y:80})
})

test('data reset and Escape deactivate; teardown removes all handlers', () => {
  const f = fixture()
  const controller = installClickChartTooltip(f.chart, f.container)
  f.listeners.get('keydown')({key:'Enter'})
  assert.equal(f.actions.length, 0)
  for (const dismiss of [()=>f.listeners.get('keydown')({key:'Escape'}),()=>controller.hide()]) {
    f.rendererListeners.get('click')({offsetX:100,offsetY:80})
    dismiss()
    f.actions.length = 0
    f.rendererListeners.get('mousemove')({offsetX:200,offsetY:80})
    assert.deepEqual(f.actions, [])
  }
  controller.dispose()
  assert.equal(f.listeners.size + f.rendererListeners.size + f.chartListeners.size, 0)
})
