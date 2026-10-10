import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import vm from 'node:vm'
import ts from 'typescript'
import {parse,compileScript} from '@vue/compiler-sfc'
import * as vue from 'vue'
import * as pinia from 'pinia'
import * as tasks from '../src/task-execution.ts'
import * as saved from '../src/saved-strategy-input.ts'
import * as market from '../src/market.ts'
import * as research from '../src/research-input.ts'
import * as execution from '../src/execution-context.ts'
import {connectStrategyPicker} from './strategy-picker-harness.mjs'

const require=createRequire(import.meta.url),copy=v=>JSON.parse(JSON.stringify(v)),tick=()=>new Promise(setImmediate)
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
const portfolio=()=>({id:'saved-1',name:'QA',kind:'portfolio',strategy:'ma_cross',params:{fast:7,slow:31},context:{stocks:['SZ:300450','SH:600699'],category:'DAY',adjust:'QFQ',start_date:'2025-01-02',end_date:'2026-09-30'},trade_config:{cash:200000,commission:.0002,min_commission:1.23,stamp_tax:.0005,slippage:.002,execution:'next_close'}})
const result=()=>({total_performance:{total_return:.123456},individual_results:{},combined_equity:[],equity_allocation:{}})
function execute(file,mocks,sfc=false){
  const source=readFileSync(file,'utf8'),content=sfc?compileScript(parse(source,{filename:file.pathname}).descriptor,{id:'qa'}).content:source
  const output=ts.transpileModule(content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
  const mod={exports:{}}
  vm.runInNewContext(output,{exports:mod.exports,module:mod,AbortController,setTimeout,clearTimeout,confirm:()=>true,
    require:path=>mocks[path]??(path.endsWith('.vue')?{}:require(path))},{filename:file.pathname})
  return mod.exports
}
function mount(name='PortfolioView',api={}){
  const owner=vue.ref({id:'alice'}),stock=vue.ref('300450'),adjust=vue.ref('HFQ'),history=[]
  const route=vue.reactive({path:'/portfolio',fullPath:'/portfolio?savedStrategyId=saved-1',query:{savedStrategyId:'saved-1'}})
  const starts=[],stops=[],calls=[]
  const defaults={fetchSavedStrategy:async()=>portfolio(),saveStrategy:async()=>portfolio(),fetchStrategies:async()=>({strategies:[{name:'ma_cross',label:'MA',params:[]}]}),
    submitPortfolioTask:async()=>({task_id:'qa'}),submitMultiStrategyTask:async()=>({task_id:'qa'}),submitOptimizeTask:async()=>({task_id:'qa'}),submitOptimizeAllTask:async()=>({task_id:'qa'}),
    fetchTask:async()=>({task_id:'qa',status:'done',result:result()}),fetchSavedStrategies:async()=>({strategies:[]}),fetchStockNames:async()=>({}),deleteSavedStrategy:async()=>{},
  }
  const apiMock={formatError:e=>String(e.message??e),...Object.fromEntries(Object.keys(defaults).map(key=>[key,(...args)=>{calls.push({name:key,args});return(api[key]??defaults[key])(...args)}]))}
  const mocks={vue:{...vue,onMounted:f=>starts.push(f),onBeforeUnmount:f=>stops.push(f)},pinia,'../api':apiMock,'../task-execution':tasks,'../research-input':research,
    '../auth':{useAuth:()=>({currentUser:owner})},'vue-router':{useRoute:()=>route,useRouter:()=>({push:value=>calls.push({name:'navigate',args:[value]})})},
    '../market-preferences':{useMarketPreferences:()=>({adjustMode:adjust})},'../stock-history':{getLastStockCode:()=>stock.value,useSelectedStock:()=>stock,recordStockHistory:r=>history.push(r)},'../market':market,
    '../mobile-settings':{useMobileSettings:()=>({mobile:vue.ref(false),settingsOpen:vue.ref(false)})},'../saved-strategy-input':saved,'../execution-context':execution,
    '../grading':{gradePortfolio:()=>null,gradeOptimizationPoint:()=>null},'../metric-state':{metricText:()=>''},
    '../performance-context':{performanceSnapshot:value=>value,portfolioBasis:()=>null},
  }
  const p=pinia.createPinia();pinia.setActivePinia(p)
  const store=execute(new URL('../src/stores/backtest.ts',import.meta.url),mocks).useBacktestStore()
  mocks['../stores/backtest']={useBacktestStore:()=>store}
  const mod=execute(new URL(`../src/views/${name}.vue`,import.meta.url),mocks,true),scope=vue.effectScope()
  const state=scope.run(()=>mod.default.setup({},{expose(){}}))
  if(name==='PortfolioView')scope.run(()=>connectStrategyPicker(state,store))
  return{state,store,owner,adjust,route,stock,calls,history,start:async()=>{for(const f of starts)await f()},close:()=>{stops.forEach(f=>f());scope.stop();store.clearPortfolio();store.clearMultiStrategy();store.clearOptimize();pinia.disposePinia(p)}}
}
test('library original/extended multi replay uses saved costs despite global preference changes',async()=>{
  const h=mount('StrategiesView')
  try{
    h.state.builtinStrategies.value=[{name:'ma_cross',label:'MA'}];h.adjust.value='HFQ'
    const p=portfolio(),saved={...p,kind:'multi',context:{cash:p.trade_config.cash,adjust:'QFQ',items:[{symbol:'SZ:300450',strategy:'ma_cross',params:p.params,category:'DAY',start_date:'2025-01-02',end_date:'2026-09-30'}]}}
    await h.state.onLoadMulti(saved,false);await h.state.onLoadMulti(saved,true)
    const requests=h.calls.filter(c=>c.name==='submitMultiStrategyTask').map(c=>c.args[0])
    assert.equal(requests.length,2)
    for(const request of requests){for(const [key,value] of Object.entries(p.trade_config))assert.equal(request[key],value);assert.equal(request.adjust,'QFQ')}
    assert.equal(requests[0].items[0].end_date,'2026-09-30');assert.equal(requests[1].items[0].end_date,h.state.isoToday())
  }finally{h.close()}
})
test('portfolio load -> actual store task lifecycle -> save uses identical context and all costs',async()=>{
  const h=mount()
  try{
    await h.start();assert.equal(h.state.savedState.value,'ready');assert.equal(h.calls.filter(c=>c.name==='submitPortfolioTask').length,0)
    await h.state.onRun();h.state.openSaveForm();await h.state.onSave()
    const sent=h.calls.find(c=>c.name==='saveStrategy').args
    for(const key of ['context','params','trade_config'])assert.deepEqual(copy(sent[0][key]),portfolio()[key])
    assert.equal(sent[1],'alice');assert.equal(h.store.portfolioRequest.cash,200000)
  }finally{h.close()}
})
for(const change of ['input','params','owner','failure','empty'])test(`portfolio catalog-stage ${change} is isolated before saved fetch`,async()=>{
  const wait=deferred(),h=mount('PortfolioView',{fetchStrategies:()=>wait.promise})
  try{
    const load=h.start();await tick()
    await h.state.onRun();assert.equal(h.calls.filter(c=>c.name==='submitPortfolioTask').length,0)
    if(change==='input')h.state.cash.value=1234
    if(change==='params')h.state.params.value={fast:99}
    if(change==='owner')h.owner.value={id:'bob'}
    if(change==='failure')wait.reject(Error('catalog unavailable'))
    else wait.resolve({strategies:change==='empty'?[]:[{name:'ma_cross',params:[{name:'fast',default:5},{name:'slow',default:20}]}]})
    await load
    assert.equal(h.state.catalogLoading.value,false);assert.equal(h.state.catalogError.value,true)
    assert.equal(h.calls.filter(c=>c.name==='fetchSavedStrategy').length,0)
    assert.notEqual(h.state.savedState.value,'ready')
    if(change!=='owner')assert.match(h.store.error,/载入|目录/)
    if(change==='input')assert.equal(h.state.cash.value,1234)
    if(change==='params')assert.deepEqual(h.state.params.value,{fast:99})
    await h.state.onRun();assert.equal(h.calls.filter(c=>c.name==='submitPortfolioTask').length,0)
  }finally{h.close()}
})
for(const reset of ['input','owner','unmount'])test(`pending portfolio cannot survive ${reset}`,async()=>{
  const pending=deferred(),h=mount('PortfolioView',{fetchTask:()=>pending.promise})
  try{
    await h.start();const run=h.state.onRun();await tick()
    if(reset==='input')h.state.stampTax.value=.001
    if(reset==='owner')h.owner.value={id:'bob'}
    if(reset==='unmount')h.close()
    pending.resolve({task_id:'qa',status:'done',result:result()});await run
    assert.equal(h.store.portfolioResult,null);assert.equal(h.store.portfolioRequest,null);assert.equal(h.store.portfolioRunning,false)
    if(reset==='input')assert.match(h.state.detachedNotice.value,/后台任务未取消/)
  }finally{if(reset!=='unmount')h.close()}
})
test('store account epoch clears completed results in all four task families',async()=>{
  const h=mount()
  try{
    await h.store.runPortfolio({stocks:['SZ:300450'],strategy:'ma_cross'})
    await h.store.runMultiStrategy({items:[]});await h.store.runOptimize({strategy:'ma_cross',param_grid:{}});await h.store.runOptimizeAll({workers:1})
    h.owner.value={id:'bob'}
    for(const key of ['portfolioResult','portfolioRequest','multiStrategyResult','multiStrategyRequest','optimizeResult','optimizeRequest','optimizeAllResult','optimizeAllRequest'])assert.equal(h.store[key],null,key)
  }finally{h.close()}
})
for(const method of ['runPortfolio','runMultiStrategy','runOptimize','runOptimizeAll'])test(`${method} old account error is ignored even after switching back`,async()=>{
  const pending=deferred(),h=mount('PortfolioView',{fetchTask:()=>pending.promise})
  try{
    const run=h.store[method]({});await tick()
    h.owner.value={id:'bob'};h.owner.value={id:'alice'}
    pending.reject(Error('old account response'));await run
    assert.equal(h.store.error,'')
    for(const key of ['portfolioRunning','multiStrategyRunning','optimizeRunning','optimizeAllRunning'])assert.equal(h.store[key],false)
  }finally{h.close()}
})
test('optimizer takes an input snapshot before awaiting bars and hands off the result strategy/adjustment',async()=>{
  const h=mount('OptimizeView'),pending=deferred()
  try{
    h.state.symbolPicker.value={loadBars:()=>pending.promise}
    h.state.paramGrid.value={fast:[7],slow:[31]}
    const run=h.state.onRun();h.state.cash.value=42;pending.resolve(true);await run
    assert.equal(h.calls.filter(c=>c.name==='submitOptimizeTask').length,0)
    await h.store.runOptimize({symbol:'SZ:300450',strategy:'ma_cross',category:'DAY',adjust:'QFQ',start_date:'2025-01-02',end_date:'2026-09-30',param_grid:{fast:[7],slow:[31]}})
    h.state.strategy.value='macd';h.adjust.value='NONE'
    h.state.onViewParams({fast:7,slow:31})
    const q=h.calls.find(c=>c.name==='navigate').args[0].query
    const restored=execution.readOptimizationQuery(q,['ma_cross'])
    assert.equal(restored.strategy,'ma_cross');assert.equal(restored.adjust,'QFQ');assert.equal(restored.code,'300450')
  }finally{h.close()}
})
test('portfolio late save cannot close or annotate newly changed configuration',async()=>{
  const pending=deferred(),h=mount('PortfolioView',{saveStrategy:()=>pending.promise})
  try{
    await h.start();await h.state.onRun();h.state.openSaveForm();const save=h.state.onSave()
    h.state.cash.value=123456
    pending.resolve(portfolio());await save
    assert.equal(h.state.saveMsg.value,'');assert.equal(h.state.saving.value,false);assert.equal(h.store.portfolioResult,null)
  }finally{h.close()}
})
test('library name lookup cannot mix later input or account into a save',async()=>{
  for(const reset of ['input','owner','unmount']){
    const pending=deferred(),h=mount('StrategiesView',{fetchStockNames:()=>pending.promise})
    try{
      h.state.builtinStrategies.value=[{name:'ma_cross',label:'MA'}];h.state.templateStrategy.value='ma_cross';h.state.templateParams.value={fast:7,slow:31}
      const save=h.state.createFromBuiltin();await tick()
      if(reset==='input')h.state.templateCode.value='600699'
      if(reset==='owner')h.owner.value={id:'bob'}
      if(reset==='unmount')h.close()
      pending.resolve({300450:'先导智能'});await save
      assert.equal(h.calls.filter(c=>c.name==='saveStrategy').length,0);assert.equal(h.history.length,0)
    }finally{if(reset!=='unmount')h.close()}
  }
})
test('library saves a multi result with submitted adjustment, not the later global preference',async()=>{
  const h=mount('StrategiesView')
  try{
    await h.store.runMultiStrategy({items:[{symbol:'SZ:300450',strategy:'ma_cross',params:{fast:7}}],cash:123456,adjust:'QFQ'})
    h.adjust.value='NONE';h.state.openSaveCombo();await h.state.submitSaveCombo()
    const sent=h.calls.find(c=>c.name==='saveStrategy').args
    assert.equal(sent[0].context.adjust,'QFQ');assert.equal(sent[0].trade_config.cash,123456);assert.equal(sent[1],'alice')
  }finally{h.close()}
})
test('late library list cannot replace a newly created record and owner change clears all personal rows',async()=>{
  const pending=deferred(),h=mount('StrategiesView',{fetchSavedStrategies:()=>pending.promise})
  try{
    const load=h.state.load();h.state.builtinStrategies.value=[{name:'ma_cross',label:'MA'}];h.state.templateStrategy.value='ma_cross'
    await h.state.createFromBuiltin();pending.resolve({strategies:[]});await load
    assert.equal(h.state.strategies.value.length,1)
    h.owner.value={id:'bob'};assert.equal(h.state.strategies.value.length,0)
  }finally{h.close()}
})
test('portfolio identity rejects mixed markets, repeats and invalid lengths',()=>{
  const defaults={category:'DAY',adjust:'QFQ',startDate:'2025-01-02',endDate:'2026-09-30',cash:1,commission:0,minCommission:0,stampTax:0,slippage:0,execution:'next_open'}
  for(const stocks of [[],['SZ:510300'],['SH:000001'],['SZ:300450','SZ:300450'],Array(21).fill('SZ:300450')]){
    const r=portfolio();r.context.stocks=stocks;assert.throws(()=>saved.savedPortfolioInput(r,defaults,['ma_cross']))
  }
})
