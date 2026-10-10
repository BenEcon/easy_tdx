import test from 'node:test'
import assert from 'node:assert/strict'
import { prepareArchiveImport } from '../src/archive-import.ts'

const bars=[{datetime:'2026-10-09 00:00:00',open:1.123456789,close:2,high:3,low:1}]
const chart=()=>({schema:1,id:'old-local-id',owner:'old-account',name:'原研究',note:'原备注',title:'300750',cutoff:'2026-10-09 15:00:00',savedAt:'2026-10-09T08:00:00Z',frontendVersion:'old-version',ruleVersions:[2026100414],
  target:{kind:'stock',code:'300750'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},
  charts:[{category:'DAY',bars:structuredClone(bars),metadata:{actual_adjust:'QFQ',observed_at:'2026-10-09 16:00:00'},result:{code:'300750',frequency:'day',bis:[],xds:[],zss:[],bcs:[],mmds:[],unknown_future:{rule:'retain'}}}]})
const study=()=>({format:'chanlun-research-snapshot-v2',code:'300750',as_of:'2026-10-09 15:00:00',result:{rows:[{category:'DAY',pairs:{ma:{fast:1.123456789}}},{category:'WEEK',error:'缺行情'}]},series:[{category:'DAY',snapshot:{bars:structuredClone(bars),metadata:{actual_adjust:'QFQ'}}}],primary:{category:'DAY'},warmup_policy:'原版'})
const envelope=payload=>({id:'00000000-0000-4000-8000-000000000001',kind:'chart',name:'云端改名',note:'云端备注',revision:3,state:'active',digest:'a'.repeat(64),size_bytes:100,created_at:'2026-10-09T08:00:00Z',updated_at:'2026-10-09T09:00:00Z',deleted_at:null,provenance:'client_archive_not_server_verified',payload})

test('legacy local migration keeps original payload, precision, versions and unknown fields without upgrading',()=>{
  const source=chart(),copy=structuredClone(source),{owner,...expected}=copy
  const prepared=prepareArchiveImport(source,'backup.json')
  assert.deepEqual(prepared.draft.payload,expected)
  assert.deepEqual(source,copy)
  assert.equal(prepared.draft.kind,'chart')
  assert.equal(prepared.draft.payload.charts[0].frozenIndicators,undefined)
  assert.match(prepared.warnings.join(' '),/旧档缺少冻结指标/)
  source.charts[0].bars[0].open=99
  assert.equal(prepared.draft.payload.charts[0].bars[0].open,1.123456789)
})
test('cloud exports use latest metadata but retain the original immutable payload, not old cloud ID/revision',()=>{
  const payload=chart();delete payload.owner
  const imported=prepareArchiveImport(envelope(payload),'cloud.json')
  assert.equal(imported.draft.name,'云端改名');assert.equal(imported.draft.note,'云端备注')
  assert.deepEqual(imported.draft.payload,payload)
  assert.equal(imported.draft.id,undefined);assert.equal(imported.draft.revision,undefined)
  assert.throws(()=>prepareArchiveImport({...envelope(payload),kind:'study'},'bad.json'),/类型与正文不一致/)
  assert.throws(()=>prepareArchiveImport({...envelope(payload),state:'purged'},'bad.json'))
})
test('study import preserves successful and failed periods plus original warmup and primary metadata',()=>{
  const original=study(),imported=prepareArchiveImport(original,'五周期研究.json')
  assert.equal(imported.draft.kind,'study');assert.equal(imported.draft.name,'五周期研究')
  assert.deepEqual(imported.draft.payload,original)
  for(const change of [v=>v.series=[],v=>v.series.push(v.series[0]),v=>v.result.rows.push(v.result.rows[0]),
    v=>delete v.result.rows[1].error,v=>v.series[0].snapshot.bars[0].low=9,v=>v.series[0].snapshot.bars[0].datetime='bad',v=>v.series[0].snapshot.bars.push(v.series[0].snapshot.bars[0])]){
    const invalid=study();change(invalid);assert.throws(()=>prepareArchiveImport(invalid,'bad.json'))
  }
})
test('unknown, incomplete, oversized and nonfinite backups are rejected, never uploaded as summaries',()=>{
  for(const source of [null,[],{}, {format:'new-version'}, {...chart(),schema:2}, {...chart(),charts:[]}, {...chart(),price:Infinity}])assert.throws(()=>prepareArchiveImport(source,'bad.json'))
  assert.throws(()=>prepareArchiveImport({...chart(),unknown:'x'.repeat(25*1024*1024)},'large.json'),/25MiB/)
})
