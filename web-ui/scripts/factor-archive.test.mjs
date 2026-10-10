import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {ref,watch} from 'vue'
import {validateFactorArchive,factorArchiveDraft} from '../src/factor-archive.ts'
import {prepareArchiveImport} from '../src/archive-import.ts'
import {freezeArchiveDraft,validateArchiveRecord} from '../src/cloud-archives.ts'
const fixture=JSON.parse(readFileSync(new URL('../../tests/fixtures/factor_archive/series.json',import.meta.url),'utf8'))
test('real frozen result archives preserve every input, missing tag, precision and failed factor',()=>{
  const source=structuredClone(fixture),before=structuredClone(source)
  assert.equal(validateFactorArchive(source),source)
  const draft=factorArchiveDraft('series',source.result)
  assert.equal(draft.kind,'factor');assert.deepEqual(draft.payload.result,source.result)
  assert.deepEqual(source,before)
  source.result.rows[0].alpha158_vwap0=123
  assert.notEqual(draft.payload.result.rows[0].alpha158_vwap0,123)
  const imported=prepareArchiveImport(draft.payload,'factor.json')
  assert.deepEqual(imported.draft.payload,draft.payload)
  assert.equal(imported.draft.kind,'factor');assert.match(imported.warnings.join(' '),/不自动取数或重算/)
  assert.equal(imported.draft.payload.result.factor_definitions.alpha158_ma5.resolved_parameters.window,13)
  assert.ok(imported.draft.payload.result.errors.pe_ratio)
})
test('factor cloud envelope imports as independent copy without original identity',()=>{
  const source={id:'00000000-0000-4000-8000-000000000001',kind:'factor',name:'改名',note:'备注',revision:1,state:'active',digest:'a'.repeat(64),size_bytes:100,created_at:'2026-10-10T08:00:00Z',updated_at:'2026-10-10T08:00:00Z',deleted_at:null,provenance:'client_archive_not_server_verified',payload:fixture}
  validateArchiveRecord(source,true)
  const imported=prepareArchiveImport(source,'factor.json')
  assert.equal(imported.draft.name,'改名');assert.equal(imported.draft.id,undefined)
  assert.throws(()=>prepareArchiveImport({...source,kind:'chart'},'wrong.json'),/类型与正文不一致/)
})
test('partial or incompatible archives fail explicitly, not repaired from the current catalog',()=>{
  for(const mutate of [p=>delete p.result.input_snapshots,p=>p.result.rows.pop(),p=>p.result.errors={},p=>p.result.settings.code='300750',p=>p.result.settings.adjust='QFQ',p=>delete p.result.factor_definitions.alpha158_ma5.resolved_parameters,p=>p.result.input_snapshots[0].index.values.pop(),p=>p.result.output_truncated=true,p=>p.result.rows[0].alpha158_vwap0=Infinity]){
    const source=structuredClone(fixture);mutate(source);assert.throws(()=>validateFactorArchive(source))
  }
  assert.throws(()=>freezeArchiveDraft({kind:'factor',name:'过大',note:'',payload:{...fixture,extra:'x'.repeat(25*1024*1024)}}),/25MiB/)
})
test('read-only renderer has no execution or market API imports; explicit replay is separate',()=>{
  const source=readFileSync(new URL('../src/components/FactorArchivePreview.vue',import.meta.url),'utf8')
  assert.doesNotMatch(source,/\bfetch\(|from ['"].*\/api['"]|onMounted|computeResearchFactors/)
  const recompute=readFileSync(new URL('../src/components/FactorArchiveRecompute.vue',import.meta.url),'utf8')
  assert.match(recompute,/!confirmed.value/);assert.match(recompute,/source_archive_id/)
  assert.match(recompute,/crypto.randomUUID\(\)/);assert.match(recompute,/expected_revision:source.revision\},true\)/)
  assert.match(recompute,/currentUser.value\?\.id!==owner/);assert.match(recompute,/onBeforeUnmount\(reset\)/)
  assert.match(recompute,/watch\(\[\(\)=>props.record.id,\(\)=>props.record.digest,\(\)=>props.record.revision,\(\)=>currentUser.value\?\.id\]/)
})
test('same-account profile refresh preserves replay state; identity changes invalidate synchronously',()=>{
  const currentUser=ref({id:'alice',profile:1}),record=ref({id:'archive',digest:'abc'});let resets=0
  const stop=watch([()=>record.value.id,()=>record.value.digest,()=>currentUser.value?.id],()=>{resets++},{flush:'sync'})
  currentUser.value={id:'alice',profile:2};assert.equal(resets,0)
  currentUser.value={id:'bob',profile:1};assert.equal(resets,1)
  record.value={id:'archive',digest:'new'};assert.equal(resets,2);stop()
})
