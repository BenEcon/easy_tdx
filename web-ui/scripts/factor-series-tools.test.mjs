import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {computed,effectScope,ref} from 'vue'
import {factorFavoriteState,parseFactorFavorites,FACTOR_FAVORITES_KEY} from '../src/factor-favorites.ts'
import {factorSeriesOptions,reconcileTracks} from '../src/factor-series-chart.ts'
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
function favorites(){
  const user=ref({id:'alice',preferences:{adjust_mode:'QFQ',[FACTOR_FAVORITES_KEY]:['rsi_14']}}),calls=[],scope=effectScope()
  const state=scope.run(()=>factorFavoriteState(user,async patch=>{const d=deferred(),owner=user.value?.id;calls.push({owner,patch,...d});await d.promise;if(user.value?.id===owner)user.value={...user.value,preferences:{...user.value.preferences,...patch}}}))
  return{user,calls,state,close:()=>scope.stop()}
}
test('favorite IDs are bounded, deduplicated and malformed saved preferences never get overwritten',async()=>{
  assert.deepEqual(parseFactorFavorites(undefined),[])
  assert.deepEqual(parseFactorFavorites(['rsi_14','rsi_14','future_library_1']),['rsi_14','future_library_1'])
  for(const x of [null,{},['<script>'],[1],Array(513).fill('rsi_14')])assert.throws(()=>parseFactorFavorites(x))
  const h=favorites();try{h.user.value.preferences[FACTOR_FAVORITES_KEY]=null;await h.state.toggle('rsi_14');assert.equal(h.calls.length,0);assert.match(h.state.message.value,/格式异常/)}finally{h.close()}
})
test('favorites use acknowledgment and only patch their own key; same-session writes serialize',async()=>{
  const h=favorites();try{
    const a=h.state.toggle('momentum_20d');assert.equal(h.state.saving.value,true)
    assert.deepEqual(h.state.items.value,['rsi_14'])
    await h.state.toggle('volatility_20d');assert.equal(h.calls.length,1)
    assert.deepEqual(Object.keys(h.calls[0].patch),[FACTOR_FAVORITES_KEY]);h.calls[0].resolve();await a
    assert.deepEqual(h.state.items.value,['rsi_14','momentum_20d']);assert.equal(h.user.value.preferences.adjust_mode,'QFQ')
    const b=h.state.toggle('rsi_14');h.calls[1].resolve();await b;assert.deepEqual(h.state.items.value,['momentum_20d'])
  }finally{h.close()}
})
test('failed favorite updates do not pretend success and can retry',async()=>{
  const h=favorites();try{const a=h.state.toggle('momentum_20d');h.calls[0].reject(Error('offline'));await a;assert.deepEqual(h.state.items.value,['rsi_14']);assert.match(h.state.message.value,/offline/);assert.equal(h.state.saving.value,false);const b=h.state.toggle('momentum_20d');h.calls[1].resolve();await b;assert.equal(h.state.message.value,'');assert.equal(h.state.items.value.length,2)}finally{h.close()}
})
test('other preference acknowledgment exposing pending patch cannot fake a saved favorite',async()=>{
  const h=favorites();try{
    const save=h.state.toggle('momentum_20d')
    h.user.value={...h.user.value,preferences:{...h.user.value.preferences,[FACTOR_FAVORITES_KEY]:['rsi_14','momentum_20d']}}
    assert.deepEqual(h.state.items.value,['rsi_14'])
    h.calls[0].reject(Error('transport failed'));await save
    assert.deepEqual(h.state.items.value,['rsi_14']);assert.match(h.state.message.value,/未保存/)
  }finally{h.close()}
})
test('owner switch clears state immediately and old failure cannot affect new save',async()=>{
  const h=favorites();try{
    const a=h.state.toggle('momentum_20d');h.user.value={id:'bob',preferences:{[FACTOR_FAVORITES_KEY]:['obv_trend']}}
    assert.deepEqual(h.state.items.value,['obv_trend']);assert.equal(h.state.saving.value,false)
    const b=h.state.toggle('rsi_14');h.calls[0].reject(Error('alice expired'));await a
    assert.equal(h.state.saving.value,true);assert.equal(h.state.message.value,'');h.calls[1].resolve();await b
    assert.deepEqual(h.state.items.value,['obv_trend','rsi_14'])
    h.user.value=null;assert.deepEqual(h.state.items.value,[]);await h.state.toggle('rsi_14');assert.equal(h.calls.length,2);assert.match(h.state.message.value,/请先登录/)
  }finally{h.close()}
})
test('series compare shares all x axes but preserves independent raw values, scales, gaps and tooltip precision',()=>{
  const tracks=[{id:'a',name:'a',values:[1e-9,null,2e-9]},{id:'b',name:'b',values:[40,NaN,50]},{id:'c',name:'c',values:[-3,0,3]}],before=structuredClone(tracks)
  const o=factorSeriesOptions(['d1','d2','d3'],tracks,'raw')
  assert.equal(o.grid.length,3);assert.equal(o.yAxis.length,3)
  o.series.forEach((s,i)=>{assert.equal(s.yAxisIndex,i);assert.equal(s.xAxisIndex,i);assert.equal(s.connectNulls,false)})
  assert.deepEqual(o.series.map(s=>s.data),[[1e-9,null,2e-9],[40,null,50],[-3,0,3]])
  assert.deepEqual(o.dataZoom.map(z=>z.xAxisIndex),[[0,1,2],[0,1,2]])
  assert.ok(o.dataZoom.every(z=>z.filterMode==='none'));assert.equal(o.axisPointer.link[0].xAxisIndex,'all')
  assert.ok(o.yAxis.every(y=>y.scale===true&&y.min===undefined&&y.max===undefined))
  assert.equal(o.tooltip.valueFormatter(1e-9),String(1e-9));assert.equal(o.yAxis[0].axisLabel.formatter(1e-9),'1e-9')
  assert.notEqual(o.yAxis[0].axisLabel.formatter(.010),o.yAxis[0].axisLabel.formatter(.014))
  assert.equal(o.tooltip.formatter([{dataIndex:1}]),'d2\n{s0|●} a  —\n{s1|●} b  —\n{s2|●} c  0')
  assert.equal(o.tooltip.formatter([{dataIndex:99}]),'')
  assert.equal(o.xAxis[2].axisLabel.formatter('2026-10-10T00:00:00'),'2026-10-10')
  assert.deepEqual(tracks,before)
})
test('future appending leaves prior plotted values unchanged, missing is never replaced by zero',()=>{
  const t=[{id:'a',name:'A',values:[null,1.123456789]}],o=factorSeriesOptions(['d1','d2'],t)
  const newer=factorSeriesOptions(['d1','d2','d3'],[{...t[0],values:[...t[0].values,10000]}])
  assert.deepEqual(newer.series[0].data.slice(0,2),o.series[0].data)
  assert.deepEqual(reconcileTracks(['a','a','b','unknown'],['a','b']),['a','b'])
  for(const entries of [[],Array(5).fill(t[0]),[t[0],t[0]],[{...t[0],values:[]}]])assert.throws(()=>factorSeriesOptions(['d1','d2'],entries))
})
test('multi-factor comparison is reused in live and read-only views, favorites do not change research settings',()=>{
  const load=n=>readFileSync(new URL(`../src/${n}`,import.meta.url),'utf8')
  for(const file of ['views/QuantResearchView.vue','components/FactorArchivePreview.vue'])assert.match(load(file),/<FactorSeriesComparison/)
  for(const file of ['views/QuantResearchView.vue','components/FactorEvaluationPanel.vue']){const s=load(file);assert.match(s,/useFactorFavorites/);assert.match(s,/canonical_name/);assert.match(s,/onlyFavorites/)}
  const chart=load('components/FactorSeriesComparison.vue');assert.match(chart,/ChartFrame/);assert.match(chart,/useChartResize/);assert.match(chart,/onBeforeUnmount/);assert.doesNotMatch(chart,/fetch|computeResearch|updatePreferences|normalize/)
  assert.match(load('use-factor-favorites.ts'),/effectScope\(true\)/)
})
