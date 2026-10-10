import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { readStructureSettings, structureSettingsLabel } from '../src/structure-settings.ts'
import { evidenceReplayRequest } from '../src/evidence-replay.ts'

test('defaults and bounded settings never expose strict price overrides', () => {
  assert.deepEqual(readStructureSettings(), {bi_type:'new',zs_min_lines:3})
  for (const bi_type of ['new','old','simple']) for (const zs_min_lines of [3,4,5,6])
    assert.deepEqual(readStructureSettings({bi_type,zs_min_lines}), {bi_type,zs_min_lines})
  for (const s of [null,{}, {bi_type:'new',zs_min_lines:2}, {bi_type:'old',zs_min_lines:4.5},
    {bi_type:'new',zs_min_lines:'3'}, {bi_type:'new',zs_min_lines:3,fx_strict:false}]) assert.throws(()=>readStructureSettings(s))
  assert.match(structureSettingsLabel({bi_type:'old',zs_min_lines:4}), /老笔.*4/)
})
test('evidence replay uses its own frozen period settings', () => {
  const settings={bi_type:'old',zs_min_lines:5}
  const result=evidenceReplayRequest({category:'DAY',bars:[{is_closed:true}],result:{code:'test',structure_settings:settings}},1)
  assert.deepEqual(result.structure_settings,settings)
})
test('settings disclosure is closed by default and reuses existing controls',()=>{
  const source=readFileSync(new URL('../src/views/ChanlunView.vue',import.meta.url),'utf8')
  assert.match(source,/<details class="inspector-section structure-settings-section">/)
  assert.match(source,/aria-label="成笔规则"/)
  assert.match(source,/aria-label="基础中枢最少线段数"/)
  assert.match(source,/watch\(structureSettings/)
})
