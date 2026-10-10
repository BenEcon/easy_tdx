import test from 'node:test'
import assert from 'node:assert/strict'
import {validateArchiveChartResult} from '../src/archive-chart-validation.ts'
import {segmentEvidence,centreEvidence} from '../src/structure-evidence.ts'
import {divergenceEvidence,signalEvidence,waveDiagnosticLines,waveComparisonLines} from '../src/divergence-evidence.ts'

const date='2026-10-08 15:00',end='2026-10-09 15:00'
const feature=()=>({low:10,high:12,pen_indices:[0],high_pen:0,low_pen:0})
const segment=()=>({index:0,direction:'up',low:10,high:12,start_date:date,end_date:end,done:true,
  evidence:{case:'no_gap_fractal',start_pen:0,end_pen:2,features:[feature()],reverse_features:[]}})
const centre=()=>({index:0,line_count:3,zd:10,zg:12,dd:9,gg:13,done:false,start_date:date,end_date:end,
  seed_segments:[0,1,2],member_segments:[0,1,2],relation_history:[{known_date:end,previous_centre:0,relation:'overlapping',both_exited:false,envelope_overlap:[10,11]}],
  transitions:[{state:'formed',segment_index:2,known_date:end}]})
const check=()=>({gate:'shrinking_same_colour_area',passed:true,values:{a_area:2,c_area:1.123456789},dates:{a_extreme_index:date,c_extreme_index:end}})
const audit=()=>({dates:{known_index:end},checks:[check()],closed:true})
const event=()=>({signal_date:date,detected_date:end,status:'candidate',confirmed_date:null})
const diagnostic=()=>({...audit(),direction:'up',status:'confirmed',rejections:[{from_date:date,through_date:end,gates:['test']}],
  comparisons:[{...audit(),mode:'full_a',research_only:true,passed:true,events:[event()]}]})
const divergence=()=>({type:'macd',bc:true,direction:'down',curr_date:end,prev_date:date,msg:'原始记录',status:'candidate',
  evidence:{rule_version:2026100414,reverse_pen_first_formed:1,reverse_pen_start_price:10,reverse_pen_end_price:12},
  failure_audit:audit(),related_events:[event()],intervals:{a_start:date,a_end:end}})
const valid=()=>({code:'QA',frequency:'DAY',bis:[segment()],xds:[segment()],unfinished_xd:segment(),zss:[centre()],structural_centres:[centre()],
  mmds:[{type:'3buy',date:end,msg:'原始记录',source:'confirmed_segment_base_v1',evidence:{first_return:true,zd:10,zg:12}}],bcs:[divergence()],
  pen_consolidations:[{start_date:date,end_date:end,lower:10,upper:12,pen_indices:[0,1,2],confirmed:false}],wave_diagnostics:[diagnostic()],
  macd:{dif:[null,-1],dea:[null,-2],hist:[null,2]},opaque_future_tree:{children:[{anything:'retained'}]}})

test('all current chart inspector evidence stays readable without altering original nested data',t=>{
  t.mock.method(globalThis,'fetch',()=>{throw Error('unexpected recalculation')})
  const value=valid(),before=JSON.stringify(value)
  validateArchiveChartResult(value)
  for(const lines of [segmentEvidence(value.xds[0]),centreEvidence(value.zss[0]),divergenceEvidence(value.bcs[0]),signalEvidence(value.mmds[0]),waveDiagnosticLines(value.wave_diagnostics[0]),waveComparisonLines(value.wave_diagnostics[0].comparisons[0])]){
    assert.ok(lines.length);assert.ok(lines.every(line=>typeof line==='string'&&!line.includes('NaN')))
  }
  assert.equal(JSON.stringify(value),before)
})

test('reject malformed fields reachable from overlays, popovers and every inspector section with exact paths',()=>{
  const mutations=[
    [r=>r.bis[0].start_date=42,'bis[0].start_date'],[r=>r.bis[0].done='true','bis[0].done'],
    [r=>r.bis[0].direction=['up'],'bis[0].direction'],[r=>r.bis[0].high='12','bis[0].high'],
    [r=>r.xds[0].start_value=Infinity,'xds[0].start_value'],[r=>r.unfinished_xd.evidence.features=[null],'unfinished_xd.evidence.features[0]'],
    [r=>r.xds[0].evidence.features[0].pen_indices={length:1},'xds[0].evidence.features[0].pen_indices'],
    [r=>r.xds[0].evidence.features[0].low_pen=-1,'xds[0].evidence.features[0].low_pen'],
    [r=>r.structural_centres[0].relation_history[0].envelope_overlap=[10],'structural_centres[0].relation_history[0].envelope_overlap'],
    [r=>r.zss[0].transitions[0].known_date='2026-02-30','zss[0].transitions[0].known_date'],
    [r=>r.zss[0].seed_segments=[false],'zss[0].seed_segments[0]'],
    [r=>r.bcs[0].related_events[0].signal_date={},'bcs[0].related_events[0].signal_date'],
    [r=>r.bcs[0].failure_audit.checks[0].values=null,'bcs[0].failure_audit.checks[0].values'],
    [r=>r.bcs[0].failure_audit.dates=null,'bcs[0].failure_audit.dates'],
    [r=>delete r.bcs[0].evidence.reverse_pen_start_price,'bcs[0].evidence.reverse_pen_start_price'],
    [r=>r.bcs[0].evidence.price='10','bcs[0].evidence.price'],[r=>r.bcs[0].status=['confirmed'],'bcs[0].status'],
    [r=>delete r.bcs[0].direction,'bcs[0].direction'],[r=>r.bcs[0].bc='false','bcs[0].bc'],
    [r=>r.mmds[0].type='future-buy','mmds[0].type'],[r=>r.mmds[0].date={date},'mmds[0].date'],
    [r=>r.mmds[0].evidence.first_return='false','mmds[0].evidence.first_return'],
    [r=>r.pen_consolidations[0].confirmed='false','pen_consolidations[0].confirmed'],
    [r=>r.wave_diagnostics[0].checks[0].gate=1,'wave_diagnostics[0].checks[0].gate'],
    [r=>r.wave_diagnostics[0].checks[0].passed='false','wave_diagnostics[0].checks[0].passed'],
    [r=>r.wave_diagnostics[0].checks[0].values.a_area=[], 'wave_diagnostics[0].checks[0].values.a_area'],
    [r=>r.wave_diagnostics[0].rejections[0].gates={},'wave_diagnostics[0].rejections[0].gates'],
    [r=>r.wave_diagnostics[0].comparisons[0].events[0].detected_date=4,'wave_diagnostics[0].comparisons[0].events[0].detected_date'],
    [r=>r.macd.dif=[0],'macd'],[r=>r.macd.hist=[0,'2'],'macd.hist[1]'],
  ]
  for(const [mutate,path] of mutations){
    const value=valid();mutate(value);const before=structuredClone(value)
    assert.throws(()=>validateArchiveChartResult(value,'charts.DAY.result'),error=>error.message.includes(`charts.DAY.result.${path}`),path)
    assert.deepEqual(value,before,`${path}: invalid record modified`)
  }
})

test('optional old fields and empty failure checkpoints remain readable, no missing-state invention',()=>{
  const value=valid()
  delete value.bcs[0].status;value.bcs[0].failure_audit={};value.bcs[0].related_events=null
  delete value.xds[0].evidence;value.structural_centres=null;value.wave_diagnostics=null;value.macd=null
  validateArchiveChartResult(value)
  assert.equal(value.bcs[0].status,undefined)
  assert.equal(value.xds[0].evidence,undefined)
})
