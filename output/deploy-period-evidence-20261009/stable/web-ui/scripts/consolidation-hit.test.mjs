import test from 'node:test'
import assert from 'node:assert/strict'
import { consolidationHits, boundedPopover } from '../src/consolidation-hit.ts'
test('inside, border, reversed y and overlapping rectangles resolve newest first',()=>{
  const bounds=[{index:0,start:[10,80],end:[100,20]},{index:1,start:[50,90],end:[120,40]}]
  assert.deepEqual(consolidationHits(bounds,60,60),[1,0])
  assert.deepEqual(consolidationHits(bounds,10,20),[0])
  assert.deepEqual(consolidationHits(bounds,9,20),[0])
  assert.deepEqual(consolidationHits(bounds,130,60),[])
  assert.deepEqual(consolidationHits(bounds,50,130),[])
})
test('invalid or missing render coordinates cannot create hits',()=>{
  assert.deepEqual(consolidationHits([{index:0,start:[NaN,2],end:[3,4]},{index:1,start:[],end:[2,3]}],1,2),[])
  assert.deepEqual(consolidationHits([],0,0),[])
  assert.deepEqual(consolidationHits([{index:0,start:[0,0],end:[2,2]}],NaN,0),[])
})
test('popup stays within narrow viewport and near-edge right click',()=>{
  assert.deepEqual(boundedPopover(310,690,296,360,320,700),{left:12,top:328})
  assert.deepEqual(boundedPopover(100,100,340,360,1440,900),{left:110,top:110})
  assert.deepEqual(boundedPopover(-20,-20,340,360,1440,900),{left:12,top:12})
})
