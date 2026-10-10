import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {needsBenchmark,validateBenchmarkInput,validateBenchmarkPool,benchmarkOptions} from '../src/factor-benchmark.ts'

const source=()=>{
  const meta={category:'DAY',bar_time:'end',actual_adjust:'NONE',requested_adjust:'NONE',source:'MAC_INDEX',instrument:{kind:'index',market:'SH',code:'000001'}}
  const snapshot={version:'factor-input-v1',symbol:'SH:000001',columns:['datetime','open','close','is_closed'],rows:[['2026-01-05',100,99,true]],attrs:{snapshot_metadata:meta},digest:'a'.repeat(64)}
  return {columns:['datetime','benchmark_open','benchmark_close','is_closed'],rows:[['2026-01-05',100,99,true],['2026-01-06',{special:'NaN'},{special:'NaN'},true]],attrs:{snapshot_metadata:{category:'DAY',bar_time:'end'},factor_benchmark:{version:'factor-benchmark-v1',symbol:'SH:000001',name:'上证指数',alignment:'exact_observation_time_no_fill',matched_rows:1,missing_rows:1,snapshot}}}
}
test('benchmark dependency uses declared input not a guessed name',()=>{
  assert.equal(needsBenchmark(['x'],[{name:'x',inputs:['benchmark_open','close']}]),true)
  assert.equal(needsBenchmark(['gtja191_075'],[{name:'gtja191_075',inputs:['close']}]),false)
  assert.equal(benchmarkOptions.length,4)
})
test('pool rejects mixed frozen index versions, allowing different stock calendars',()=>{
  const first=source(),second=source()
  second.rows.pop();second.attrs.factor_benchmark.missing_rows=0
  validateBenchmarkPool([first,second],'SH:000001')
  second.attrs.factor_benchmark.snapshot.digest='b'.repeat(64)
  assert.throws(()=>validateBenchmarkPool([first,second],'SH:000001'),/不同版本/)
})
test('frozen exact pairing retains absent date and rejects silent fill or replacement',()=>{
  validateBenchmarkInput(source(),'SH:000001')
  for(const mutate of [x=>x.rows[1][1]=100,x=>x.rows[0][2]=98,x=>x.attrs.factor_benchmark.snapshot.attrs.snapshot_metadata.instrument.kind='stock',x=>x.attrs.factor_benchmark.matched_rows=2,x=>x.attrs.factor_benchmark=null,x=>delete x.attrs.factor_benchmark,x=>x.attrs.factor_benchmark.snapshot.attrs.factor_benchmark={}]){
    const x=source();mutate(x);assert.throws(()=>validateBenchmarkInput(x,'SH:000001'))
  }
  assert.throws(()=>validateBenchmarkInput(source(),'SZ:399001'))
})
test('failed auxiliary fetch must be explicitly recorded for both fields; legacy needs none',()=>{
  const x={columns:['datetime'],rows:[['2026-01-05']],attrs:{factor_input_errors:{benchmark_open:'failure',benchmark_close:'failure'}}}
  validateBenchmarkInput(x,'SH:000001')
  delete x.attrs.factor_input_errors.benchmark_open
  assert.throws(()=>validateBenchmarkInput(x,'SH:000001'))
  validateBenchmarkInput({columns:['datetime'],rows:[['2026-01-05']],attrs:{}},null)
})
test('UI exposes benchmark conditionally and invalidates both research paths',()=>{
  for(const file of ['views/QuantResearchView.vue','components/FactorEvaluationPanel.vue']){
    const text=readFileSync(new URL('../src/'+file,import.meta.url),'utf8')
    assert.match(text,/<FactorBenchmarkPicker v-if="benchmarkRequired" v-model="benchmark"/)
    assert.match(text,/benchmark: ?benchmarkRequired.value\?benchmark.value:null/)
    assert.match(text,/JSON.stringify\(\[[^\n]*benchmark.value/)
    assert.match(text,/benchmark.value='SH:000001'/)
  }
})
