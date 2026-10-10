import test from 'node:test'
import assert from 'node:assert/strict'
import { prepareLocalMigration, uploadLocalMigration } from '../src/archive-migration.ts'

const source = () => ({schema:1,id:'local-1',owner:'alice',name:'原研究',note:'原备注',title:'300750',cutoff:'2026-10-09 15:00:00',savedAt:'2026-10-09T08:00:00Z',frontendVersion:'old-version',ruleVersions:[2026100414],
  target:{kind:'stock',code:'300750'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},
  charts:[{category:'DAY',bars:[{datetime:'2026-10-09 00:00:00',open:1.123456789,close:2,high:3,low:1}],metadata:{actual_adjust:'QFQ',observed_at:'2026-10-09 16:00:00'},result:{code:'300750',frequency:'day',bis:[],xds:[],zss:[],bcs:[],mmds:[],unknown:{rule:'retain'}}}]})

test('migration IDs survive rescanning/reload, preserve precision and isolate owners and changed content', async()=>{
  const value=source(),original=structuredClone(value),first=await prepareLocalMigration(value,'alice')
  assert.deepEqual(await prepareLocalMigration(structuredClone(value),'alice'),first)
  assert.match(first.plan.cloudId,/^[a-f\d]{8}-[a-f\d]{4}-8[a-f\d]{3}-[89ab][a-f\d]{3}-[a-f\d]{12}$/)
  assert.deepEqual(value,original)
  const payload=JSON.parse(first.body).payload,{owner,...expected}=original
  assert.deepEqual(payload,expected)
  assert.equal(payload.charts[0].bars[0].open,1.123456789)
  assert.equal(payload.charts[0].frozenIndicators,undefined)
  assert.notEqual((await prepareLocalMigration({...value,owner:'bob'},'bob')).plan.cloudId,first.plan.cloudId)
  assert.notEqual((await prepareLocalMigration({...value,note:'新备注'},'alice')).plan.cloudId,first.plan.cloudId)
  assert.match(first.plan.warnings.join(' '),/未补算/)
})
test('migration rejects missing owners, foreign archives and malformed inputs before upload', async()=>{
  for(const value of [null,{}, {...source(),owner:'bob'}, {...source(),owner:undefined},{...source(),id:''},{...source(),charts:[]},{...source(),n:Infinity}]) {
    await assert.rejects(prepareLocalMigration(value,'alice'))
  }
  await assert.rejects(prepareLocalMigration(source(),''))
})
test('post-inspection changes never upload under a previously confirmed identity',async()=>{
  const {plan}=await prepareLocalMigration(source(),'alice')
  let sent=0
  await assert.rejects(uploadLocalMigration(plan,'alice',{valid:()=>true,read:async()=>({...source(),note:'changed'}),send:async()=>{sent++}}),/发生变化/)
  assert.equal(sent,0)
})
test('lost response retries the same immutable body and id, without automatic retry or local deletion',async()=>{
  const {plan}=await prepareLocalMigration(source(),'alice'),calls=[]
  const io={valid:()=>true,read:async()=>source(),send:async(id,body)=>{calls.push({id,body});if(calls.length===1)throw Error('network');return{id,state:'active'}}}
  await assert.rejects(uploadLocalMigration(plan,'alice',io),/network/)
  assert.equal(calls.length,1)
  const saved=await uploadLocalMigration(plan,'alice',io)
  assert.equal(saved.id,plan.cloudId);assert.deepEqual(calls[0],calls[1])
})
test('stop or account changes before/after read and upload discard stale results',async()=>{
  const {plan}=await prepareLocalMigration(source(),'alice')
  for(const stage of ['before','read','upload']){
    let active=stage!=='before',read=0,sent=0
    await assert.rejects(uploadLocalMigration(plan,'alice',{valid:()=>active,read:async()=>{read++;if(stage==='read')active=false;return source()},send:async id=>{sent++;active=false;return{id,state:'active'}}}),/停止或账户/)
    assert.equal(read,stage==='before'?0:1);assert.equal(sent,stage==='upload'?1:0)
  }
})
test('deleted cloud copies are not restored, purged copies and wrong response IDs are not treated as success',async()=>{
  const {plan}=await prepareLocalMigration(source(),'alice'),io={valid:()=>true,read:async()=>source()}
  assert.equal((await uploadLocalMigration(plan,'alice',{...io,send:async id=>({id,state:'deleted'})})).state,'deleted')
  await assert.rejects(uploadLocalMigration(plan,'alice',{...io,send:async()=>{throw Error('410 已永久删除')}}),/410/)
  await assert.rejects(uploadLocalMigration(plan,'alice',{...io,send:async()=>({id:'wrong',state:'active'})}),/不匹配/)
})
