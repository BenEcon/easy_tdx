import test from 'node:test'
import assert from 'node:assert/strict'
import {execFileSync} from 'node:child_process'
import {fileURLToPath} from 'node:url'
import {compositionConfig,compositionDefaults,assertComposition} from '../src/factor-composition.ts'
import {validateFactorArchive,factorArchiveDraft} from '../src/factor-archive.ts'

const root=fileURLToPath(new URL('../../',import.meta.url))
const payload=JSON.parse(execFileSync(`${root}.venv/bin/python`,['-c',`
import json
from pathlib import Path
from easy_tdx.factor.snapshot import restore_input
from easy_tdx.web.routers.research import FactorEvaluationRequest, evaluation_result
p=json.loads(Path('tests/fixtures/factor_archive/multi-horizon.json').read_text())
s=p['result']['settings']; s.pop('category'); s['factors']=['momentum_20d','volatility_20d']; s['factor_parameters']={}
s['composition']={'method':'rank_centered','components':[{'name':'momentum_20d','weight':3.0,'direction':1},{'name':'volatility_20d','weight':1.0,'direction':-1}]}
frames={i['symbol']:restore_input(i) for i in p['result']['input_snapshots']}
p['result']=evaluation_result(FactorEvaluationRequest.model_validate(s),frames)
print(json.dumps(p,ensure_ascii=False,allow_nan=False))
`],{cwd:root,encoding:'utf8',maxBuffer:32*1024*1024}))

test('disabled combination does not add implicit weights; enabled selection is explicit',()=>{
  assert.equal(compositionConfig(compositionDefaults(),['a','b']),null)
  const draft={enabled:true,components:{a:{weight:3,direction:1},b:{weight:1,direction:-1},stale:{weight:100,direction:1}}}
  assert.deepEqual(compositionConfig(draft,['a','b']),{method:'rank_centered',components:[{name:'a',weight:3,direction:1},{name:'b',weight:1,direction:-1}]})
  assert.throws(()=>compositionConfig(draft,['a']))
  assert.throws(()=>compositionConfig(draft,['a','a']))
  for(const weight of [0,.001,101,NaN,Infinity,'3',true])assert.throws(()=>compositionConfig({enabled:true,components:{a:{weight,direction:1}}},['a','b']))
  assert.throws(()=>compositionConfig({enabled:true,components:{a:{weight:1,direction:'-1'}}},['a','b']))
})

test('actual Python report preserves the combination through export and read-only reopen',()=>{
  const original=JSON.stringify(payload)
  const value=validateFactorArchive(payload)
  const saved=factorArchiveDraft('evaluation',value.result)
  assert.deepEqual(validateFactorArchive(JSON.parse(JSON.stringify(saved.payload))).result.composition,payload.result.composition)
  assert.equal(JSON.stringify(payload),original)
  assert.equal(value.result.composition.horizon_comparison.results.length,4)
  assert.equal(value.result.composition.trade_eligible,false)
})

test('incomplete or contradictory composition archive is rejected, never repaired',()=>{
  const mutations=[
    p=>delete p.result.settings.composition,
    p=>delete p.result.composition,
    p=>p.result.composition.effective_components[0].normalized_weight=.9,
    p=>p.result.composition.scores.pop(),
    p=>p.result.composition.scores[0].values.pop(),
    p=>p.result.composition.coverage[0].scored_assets=99,
    p=>p.result.composition.latest[0].components[0].contribution=9,
    p=>p.result.composition.horizon_comparison.results.pop(),
    p=>p.result.composition.trade_eligible=true,
    p=>p.result.settings.composition.components[0].direction=true,
  ]
  for(const change of mutations){const copy=structuredClone(payload);change(copy);assert.throws(()=>validateFactorArchive(copy))}
  assert.doesNotThrow(()=>assertComposition({},{factors:['a','b']},['a']))
})
