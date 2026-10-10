import test from 'node:test'
import assert from 'node:assert/strict'
import { floatingMenuPosition } from '../src/floating-menu.ts'

test('menus stay inside phone, keyboard and landscape viewports', () => {
  for (const width of [320,390,430,760]) for (const height of [180,360,844]) {
    for (const y of [-50,60,height-35,height+100]) {
      const viewport = { width, height, top: 30, left: 0 }
      const p = floatingMenuPosition({left:width-90,top:y,bottom:y+44,width:600}, viewport, 248)
      assert.ok(p.left>=10 && p.left+p.width<=width-10)
      assert.ok(p.top>=40 && p.top+p.maxHeight<=height+20)
      assert.ok(p.maxHeight>0)
    }
  }
})

test('near-bottom controls open upwards without changing ordinary desktop width', () => {
  const p = floatingMenuPosition({left:600,top:700,bottom:744,width:220}, {width:1440,height:800}, 248)
  assert.equal(p.width,220)
  assert.equal(p.opensAbove,true)
  assert.ok(p.top+p.maxHeight<700)
})
