import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {ref,computed,watch} from 'vue'
import {selectedHorizons,horizonView} from '../src/factor-horizons.ts'
import {validateFactorArchive,factorArchiveDraft} from '../src/factor-archive.ts'
import {evaluateResearchFactors} from '../src/api.ts'
import {queryAction} from '../src/query-origin.ts'
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/factor_archive/multi-horizon.json',import.meta.url),'utf8'))
test('horizon selection is bounded, canonical and never silently amended',()=>{
  assert.deepEqual(selectedHorizons([20,5,1,10]),[1,5,10,20])
  for(const value of [[],[5,5],[1,7],[true,5],['5'],[5.5],null])assert.throws(()=>selectedHorizons(value))
})
test('horizon view uses frozen results without changing configuration or primary report',()=>{
  const result=structuredClone(fixture.result),before=structuredClone(result)
  const view=horizonView(result,20)
  assert.equal(view.settings.horizon,5)
  assert.equal(view.reports,result.horizon_comparison.results[3].reports)
  assert.equal(view.validation,result.horizon_comparison.results[3].validation)
  assert.deepEqual(result,before)
  assert.equal(horizonView(result,99),result)
  assert.equal(horizonView(null,5),null)
})
test('all horizons survive draft/export/import and old single archives still read',()=>{
  assert.equal(validateFactorArchive(fixture),fixture)
  const draft=factorArchiveDraft('evaluation',fixture.result)
  assert.deepEqual(draft.payload.result.horizon_comparison,fixture.result.horizon_comparison)
  const old=JSON.parse(readFileSync(new URL('../../tests/fixtures/factor_archive/time-validation.json',import.meta.url),'utf8'))
  assert.equal(validateFactorArchive(old),old)
})
test('missing windows, wrong labels and disagreement with primary reports fail closed',()=>{
  for(const change of [
    r=>r.horizon_comparison.results.pop(),r=>r.horizon_comparison.results[0].horizon=5,
    r=>r.horizon_comparison.results[0].reports[0].daily[0].label_end='2000-01-01',
    r=>r.horizon_comparison.results[2].reports[0].daily[0].ic=Infinity,
    r=>r.horizon_comparison.results[1].reports[0].rank_ic_mean=-.42,
    r=>delete r.horizon_comparison,r=>r.settings.horizons=[5],
  ]){const source=structuredClone(fixture);change(source.result);assert.throws(()=>validateFactorArchive(source))}
})
test('request selection invalidates immediately; display-only switching does not',()=>{
  const selected=ref([5]),display=ref(5),owner=ref('alice');let generation=0
  const key=computed(()=>JSON.stringify([selected.value,owner.value]))
  const stop=watch(key,()=>generation++,{flush:'sync'})
  selected.value=[1,5];assert.equal(generation,1)
  display.value=1;assert.equal(generation,1)
  owner.value='bob';assert.equal(generation,2);stop()
  const source=readFileSync(new URL('../src/components/FactorEvaluationPanel.vue',import.meta.url),'utf8')
  assert.match(source,/horizon.value,horizons.value,groups.value/)
  assert.match(source,/validationConfig\(validation.value,Math.max\(\.\.\.chosen\)/)
  assert.match(source,/if\(stamp!==generation\|\|!completed\)return/)
  assert.match(source,/@select-factor="focus=\$event"/)
  assert.match(source,/:factor="active\?\.name"/)
  const panel=readFileSync(new URL('../src/components/FactorHorizonComparison.vue',import.meta.url),'utf8')
  assert.match(panel,/@click="select\(row.horizon,row.report.name\)"/)
})
test('multiple horizons dispatch one explicitly manual request with complete selection',async()=>{
  const original=globalThis.fetch,calls=[]
  globalThis.fetch=async(url,init)=>{
    calls.push({url:String(url),body:JSON.parse(init.body),origin:new Headers(init.headers).get('X-Query-Origin')})
    return new Response(JSON.stringify({data:fixture.result}),{status:200})
  }
  try{
    await queryAction(true)(()=>evaluateResearchFactors(fixture.result.settings))
    assert.equal(calls.length,1);assert.deepEqual(calls[0].body.horizons,[1,5,10,20]);assert.equal(calls[0].origin,'user')
  }finally{globalThis.fetch=original}
})
