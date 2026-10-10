import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {ref,computed,watch} from 'vue'
import {validationConfig,validationDefaults,assertValidationResult} from '../src/factor-validation.ts'
import {validateFactorArchive,factorArchiveDraft} from '../src/factor-archive.ts'
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/factor_archive/time-validation.json',import.meta.url),'utf8'))
test('time modes construct explicit configs without random dates or implied training',()=>{
  const draft=validationDefaults()
  assert.equal(validationConfig(draft,5,300),null)
  assert.deepEqual(validationConfig({...draft,mode:'walk_forward'},5,300),{mode:'walk_forward',training:'expanding',train_bars:120,validation_bars:40,test_bars:40})
  assert.deepEqual(validationConfig({...draft,mode:'holdout',trainEnd:'2025-02-01',validationEnd:'2025-03-01'},5,300),{mode:'holdout',train_end:'2025-02-01',validation_end:'2025-03-01'})
})
test('invalid dates, hidden shrinkage and numeric coercion are rejected',()=>{
  const base={...validationDefaults(),mode:'holdout'}
  for(const trainEnd of ['','2025-02-30','2025-1-1','2025-04-01'])assert.throws(()=>validationConfig({...base,trainEnd,validationEnd:'2025-03-01'},5,300))
  const rolling={...validationDefaults(),mode:'walk_forward'}
  for(const trainBars of ['120',120.5,NaN,Infinity,true,19,701])assert.throws(()=>validationConfig({...rolling,trainBars},5,800))
  assert.throws(()=>validationConfig(rolling,5,120),/不足/)
  assert.throws(()=>validationConfig({...rolling,testBars:10},20,300),/长于/)
})
test('full frozen time results survive import, draft and readonly validation unchanged',()=>{
  const before=structuredClone(fixture)
  assert.equal(validateFactorArchive(fixture),fixture)
  const draft=factorArchiveDraft('evaluation',fixture.result)
  assert.deepEqual(draft.payload.result.validation,fixture.result.validation)
  assert.deepEqual(fixture,before)
  const phases=fixture.result.validation.folds.at(-1).phases
  assert.equal(phases.at(-1).partial,true)
  assert.equal(phases.at(-1).date_count,20)
})
test('missing, mismatched and nonfinite temporal archive results fail explicitly',()=>{
  for(const change of [v=>delete v.result.validation,v=>v.result.validation.config.train_bars=100,v=>v.result.validation.folds=[],v=>v.result.validation.folds[0].phases.pop(),v=>v.result.validation.test_reports[0].daily[0].ic=Infinity]){
    const source=structuredClone(fixture);change(source);assert.throws(()=>validateFactorArchive(source))
  }
  assert.doesNotThrow(()=>assertValidationResult(undefined,undefined,['legacy']))
  assert.throws(()=>assertValidationResult(fixture.result.validation,null,['momentum_20d']))
})
test('changes invalidate synchronously; same-account profile refresh does not change split',()=>{
  const validation=ref(validationDefaults()),user=ref({id:'alice'});let generation=0
  const key=computed(()=>JSON.stringify([validation.value,user.value.id]))
  const stop=watch(key,()=>generation++,{flush:'sync'})
  validation.value.mode='walk_forward';assert.equal(generation,1)
  validation.value.trainBars=150;assert.equal(generation,2)
  user.value={id:'alice'};assert.equal(generation,2)
  user.value={id:'bob'};assert.equal(generation,3);stop()
  const source=readFileSync(new URL('../src/components/FactorEvaluationPanel.vue',import.meta.url),'utf8')
  assert.match(source,/preprocess.value,validation.value,composition.value,adjustMode.value,benchmark.value,currentUser.value\?\.id/)
  assert.match(source,/validation.value=validationDefaults\(\)/)
})
