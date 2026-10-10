import test from 'node:test'
import assert from 'node:assert/strict'
import vm from 'node:vm'
import {readFileSync} from 'node:fs'
import ts from 'typescript'
import * as vue from 'vue'
import {parse,compileScript} from '@vue/compiler-sfc'
import {createTrackingSession} from '../src/tracking-session.ts'

const tick = () => new Promise(setImmediate)
const copy = value => JSON.parse(JSON.stringify(value))
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
function app() {
  const people={alice:{id:'a',role:'admin',active:true,tracking_allowed:true,preferences:{adjust_mode:'QFQ'}},bob:{id:'b',role:'user',active:true,tracking_allowed:false,preferences:{adjust_mode:'NONE'}}}
  const saves=[],names=[],cache=new Map(),scopes=[]
  const api={
    loginAccount:async name=>copy(people[name]),logoutAccount:async()=>({ok:true}),
    saveAccountPreferences:(patch,owner)=>{const d=deferred();saves.push({patch:copy(patch),owner,...d});return d.promise},
    fetchStockNames:stocks=>{const d=deferred();names.push({stocks,...d});return d.promise},
  }
  const modules={'./api':api}
  const mockVue={...vue,effectScope:(...args)=>{const s=vue.effectScope(...args);scopes.push(s);return s}}
  function load(path) {
    if(modules[path])return modules[path]
    const source=readFileSync(new URL(`../src/${path.slice(2).replace(/\.ts$/,'')}.ts`,import.meta.url),'utf8')
    const output=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
    const module={exports:{}};modules[path]=module.exports
    vm.runInNewContext(output,{module,exports:module.exports,
      require:id=>id==='vue'?mockVue:load(id),
      localStorage:{getItem:key=>cache.get(key)??null,setItem:(key,value)=>cache.set(key,value)},
      window:{addEventListener(){}},setTimeout,clearTimeout,Promise,AbortController,fetch,Headers,
    },{filename:path})
    return module.exports
  }
  const root=vue.effectScope()
  const auth=root.run(()=>load('./auth'))
  return{load,root,auth,people,saves,names,cache,close:()=>{root.stop();scopes.forEach(s=>s.stop())}}
}

test('late preference response cannot revert a newer adjustment; queued patch is captured',async()=>{
  const h=app()
  try {
    await h.auth.login('alice','')
    const market=h.root.run(()=>h.load('./market-preferences').useMarketPreferences())
    const first=h.auth.updatePreferences({sidebar_collapsed:true});await tick()
    market.adjustMode.value='HFQ'
    const mutable={note:{text:'original'}}
    const third=h.auth.updatePreferences(mutable);mutable.note.text='changed'
    h.saves[0].resolve({...h.people.alice,preferences:{adjust_mode:'QFQ',sidebar_collapsed:true}})
    await first;await tick()
    assert.equal(market.adjustMode.value,'HFQ')
    assert.deepEqual(h.saves[1].patch,{adjust_mode:'HFQ'})
    h.saves[1].resolve({...h.people.alice,preferences:{adjust_mode:'HFQ',sidebar_collapsed:true}});await tick()
    assert.deepEqual(h.saves[2].patch,{note:{text:'original'}})
    h.saves[2].resolve({...h.people.alice,preferences:{adjust_mode:'HFQ',note:{text:'original'}}});await third
    assert.equal(market.adjustMode.value,'HFQ')
  }finally{h.close()}
})

test('account switch drops old queue, permits new account immediately and ignores late response',async()=>{
  const h=app()
  try{
    await h.auth.login('alice','')
    const a=h.auth.updatePreferences({adjust_mode:'HFQ'});const caughtA=assert.rejects(a,/旧账户/)
    const queued=h.auth.updatePreferences({private_note:'alice'});const caughtQ=assert.rejects(queued,/账户已变化/)
    await tick()
    await h.auth.login('bob','')
    const b=h.auth.updatePreferences({adjust_mode:'QFQ'});await tick()
    assert.deepEqual(h.saves.map(s=>s.owner),['a','b'])
    h.saves[1].resolve({...h.people.bob,preferences:{adjust_mode:'QFQ'}});await b
    h.saves[0].resolve({...h.people.alice,preferences:{adjust_mode:'HFQ'}})
    await Promise.all([caughtA,caughtQ])
    assert.equal(h.auth.useAuth().currentUser.value.id,'b')
    assert.equal(h.auth.useAuth().currentUser.value.preferences.adjust_mode,'QFQ')
    assert.equal(h.saves.length,2)
  }finally{h.close()}
})

test('same-account logout/login does not accept response from prior session epoch',async()=>{
  const h=app()
  try{
    await h.auth.login('alice','')
    const p=h.auth.updatePreferences({adjust_mode:'HFQ'}), rejected=assert.rejects(p,/旧账户/)
    await tick();await h.auth.logout();await h.auth.login('alice','')
    h.saves[0].resolve({...h.people.alice,preferences:{adjust_mode:'HFQ'}});await rejected
    assert.equal(h.auth.useAuth().currentUser.value.preferences.adjust_mode,'QFQ')
  }finally{h.close()}
})

test('failed saves reject caller, do not wedge queue or restore stale role permissions',async()=>{
  const h=app()
  try{
    await h.auth.login('alice','')
    const first=h.auth.updatePreferences({bad:'fail'}), rejected=assert.rejects(first,/offline/)
    const second=h.auth.updatePreferences({adjust_mode:'NONE'})
    await tick();h.saves[0].reject(Error('offline'));await rejected;await tick()
    h.auth.applyActivityAccess('a',{tracking_allowed:false,active:true,role:'user'})
    h.saves[1].resolve({...h.people.alice,preferences:{adjust_mode:'NONE'}});await second
    assert.equal(h.auth.useAuth().currentUser.value.role,'user')
    assert.equal(h.auth.useAuth().currentUser.value.tracking_allowed,false)
    assert.deepEqual(copy(h.auth.useAuth().currentUser.value.preferences),{adjust_mode:'NONE'})
  }finally{h.close()}
})

test('mismatched response owner and logged-out saves are rejected',async()=>{
  const h=app()
  try{
    await assert.rejects(h.auth.updatePreferences({x:1}),/未登录/)
    await h.auth.login('alice','')
    const p=h.auth.updatePreferences({x:1}), rejected=assert.rejects(p,/旧账户/)
    await tick();h.saves[0].resolve(h.people.bob);await rejected
    assert.equal(h.auth.useAuth().currentUser.value.id,'a')
  }finally{h.close()}
})

test('market preference watcher survives the first route unmount and follows owner changes',async()=>{
  const h=app()
  try{
    await h.auth.login('alice','')
    const route=vue.effectScope()
    const market=route.run(()=>h.load('./market-preferences').useMarketPreferences())
    route.stop();await h.auth.login('bob','')
    assert.equal(market.adjustMode.value,'NONE')
  }finally{h.close()}
})

test('tracking ownership watcher survives route scope disposal and clears on revocation or logout',async()=>{
  const h=app()
  try {
    await h.auth.login('alice','')
    const route=vue.effectScope()
    const job=route.run(()=>h.load('./tracking-background').trackingSession)
    assert.equal(job.owner.value,'a');route.stop()
    job.phase.value='分析完成';job.rows.value=[{state:'done'}]
    h.auth.applyActivityAccess('a',{role:'user',active:true,tracking_allowed:false})
    assert.equal(job.owner.value,'');assert.equal(job.rows.value.length,0);assert.equal(job.phase.value,'')
    await h.auth.login('alice','');assert.equal(job.owner.value,'a')
    await h.auth.logout();assert.equal(job.owner.value,'')
  } finally {h.close()}
})

test('late name hydration cannot write across accounts; new owner hydrates independently',async()=>{
  const h=app()
  try{
    const item={code:'000001',category:'DAY',usedAt:'2026-10-10T00:00:00Z'}
    h.people.alice.preferences.stock_history=[item]
    h.people.bob.preferences.stock_history=[item]
    await h.auth.login('alice','')
    const history=h.root.run(()=>h.load('./stock-history'))
    await tick();assert.equal(h.names.length,1)
    await h.auth.login('bob','');await tick();assert.equal(h.names.length,2)
    h.names[0].resolve({'000001':'old Alice name'});await tick()
    assert.equal(h.saves.length,0)
    h.names[1].resolve({'000001':'Bob name'});await tick()
    assert.equal(h.saves[0].owner,'b')
    assert.equal(h.saves[0].patch.stock_history[0].name,'Bob name')
    assert.equal(history.useStockHistory().stockHistory.value[0].name,'Bob name')
    h.saves[0].resolve({...h.people.bob,preferences:{...h.people.bob.preferences,...h.saves[0].patch}});await tick()
  }finally{h.close()}
})

test('sidebar hydration never writes, old-owner timers cancel, failures are handled',async()=>{
  const user=vue.ref({id:'a',preferences:{sidebar_collapsed:false}}),calls=[],timers=new Map(),stops=[]
  let nextTimer=0
  const source=readFileSync(new URL('../src/App.vue',import.meta.url),'utf8')
  const script=compileScript(parse(source).descriptor,{id:'app-preference-test'})
  const output=ts.transpileModule(script.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
  const modules={
    vue:{...vue,onBeforeUnmount:f=>stops.push(f)},
    'vue-router':{useRoute:()=>({meta:{public:true}}),useRouter:()=>({replace:async()=>{}})},
    './auth':{useAuth:()=>({currentUser:user}),updatePreferences:patch=>{calls.push(copy(patch));return Promise.reject(Error('offline'))}},
    './mobile-viewport':{useMobileViewport:()=>vue.ref(false)},
    './visible-viewport':{useVisibleViewport:()=>{}},
    './use-activity':{useActivity:()=>{}},'./feature-access':{canUseTracking:()=>false},
    './tracking-background':{trackingSession:createTrackingSession()},
  }
  const module={exports:{}},scope=vue.effectScope()
  vm.runInNewContext(output,{module,exports:module.exports,require:id=>modules[id],
    localStorage:{getItem:()=>null,setItem(){}},
    setTimeout:f=>{timers.set(++nextTimer,f);return nextTimer},clearTimeout:id=>timers.delete(id),
  })
  const state=scope.run(()=>module.exports.default.setup({}, {expose(){}}))
  try{
    user.value={id:'a',preferences:{sidebar_collapsed:true}}
    assert.equal(state.sidebarCollapsed.value,true)
    assert.equal(timers.size,0)
    state.sidebarCollapsed.value=false
    user.value={id:'a',preferences:{sidebar_collapsed:true}}
    assert.equal(state.sidebarCollapsed.value,false)
    assert.equal(timers.size,1)
    user.value={id:'b',preferences:{sidebar_collapsed:true}}
    assert.equal(timers.size,0)
    state.sidebarCollapsed.value=false
    for(const callback of timers.values())callback()
    timers.clear();await tick()
    assert.deepEqual(calls,[{sidebar_collapsed:false}])
    state.sidebarCollapsed.value=true
    stops.forEach(f=>f());assert.equal(timers.size,0)
  }finally{scope.stop()}
})
