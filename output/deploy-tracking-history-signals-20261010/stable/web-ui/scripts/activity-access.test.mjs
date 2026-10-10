import test from 'node:test'
import assert from 'node:assert/strict'
import {canUseTracking} from '../src/feature-access.ts'
import {activityEligible,activityDuration,activityDetails} from '../src/activity.ts'

test('tracking is restricted to active administrators and explicitly authorized users',()=>{
  assert.equal(canUseTracking(null),false)
  assert.equal(canUseTracking({role:'admin',active:true}),true)
  assert.equal(canUseTracking({role:'user',active:true}),false)
  assert.equal(canUseTracking({role:'user',active:true,tracking_allowed:true}),true)
  assert.equal(canUseTracking({role:'user',active:true,tracking_allowed:'true'}),false)
  assert.equal(canUseTracking({role:'admin',active:false}),false)
})
test('presence requires visible focused recent interaction and never negative elapsed time',()=>{
  assert.equal(activityEligible(true,true,0,59000),true)
  for(const input of [[true,true,0,60000],[false,true,0,1],[true,false,0,1],[true,true,10,1]])assert.equal(activityEligible(...input),false)
  assert.equal(activityDuration(3661),'1 小时 1 分')
  assert.equal(activityDuration(0),'0 秒')
  assert.equal(activityDuration(NaN),'未取得')
})
test('admin query descriptions label metadata and disclose truncated targets',()=>{
  assert.equal(activityDetails({code:'300750',category:'DAY'}),'标的：300750 · 周期：DAY')
  assert.match(activityDetails({codes:['000001'],codes_total:101}),/共 101 项/)
  assert.equal(activityDetails({password:'secret'}),'无标的参数（列表或概览查询）')
})
