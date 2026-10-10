import test from 'node:test'
import assert from 'node:assert/strict'
import { canAutoStudy, researchWorkspaces, visibleComparisonPeriod, workspaceFromKey } from '../src/research-workspace.ts'
test('three workspaces are keyboard traversable without dropping an existing mode',()=>{
  assert.deepEqual(researchWorkspaces.map(item=>item.value),['chart','research','audit'])
  assert.equal(workspaceFromKey('chart','ArrowLeft'),'audit')
  assert.equal(workspaceFromKey('audit','ArrowRight'),'chart')
  assert.equal(workspaceFromKey('research','Home'),'chart')
  assert.equal(workspaceFromKey('research','End'),'audit')
  assert.equal(workspaceFromKey('research','Enter'),null)
})
test('mobile comparison shows exactly the selected snapshot; desktop shows both',()=>{
  for(const selected of ['DAY','MIN_30']) {
    assert.deepEqual(['DAY','MIN_30'].filter(p=>visibleComparisonPeriod(true,'compare',p,selected)),[selected])
    assert.equal(['DAY','MIN_30'].filter(p=>visibleComparisonPeriod(false,'compare',p,selected)).length,2)
  }
  assert.equal(visibleComparisonPeriod(true,'other','MIN_30','DAY'),true)
})
test('inactive research never starts automatic work, valid active research does',()=>{
  const valid=[true,true,false,'2026-09-30 15:00:00',5,'']
  assert.equal(canAutoStudy(...valid),true)
  for(const [index,value] of [[0,false],[1,false],[2,true],[3,''],[4,0],[5,'invalid window']]){
    const args=[...valid];args[index]=value;assert.equal(canAutoStudy(...args),false)
  }
})
