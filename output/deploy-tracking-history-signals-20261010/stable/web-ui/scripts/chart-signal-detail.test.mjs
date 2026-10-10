import test from 'node:test'
import assert from 'node:assert/strict'
import { signalName, structuralSignalDetail, macdSignalDetail } from '../src/chart-signal-detail.ts'

test('all six structural types keep extrema and confirmation separate with original evidence', () => {
  for (const type of ['1buy','2buy','3buy','1sell','2sell','3sell']) {
    const signal={type,date:'2026-10-01 10:30:00',confirmed_date:'2026-10-02 11:00:00',source:'confirmed_segment_base_v1',msg:'原始完整说明',evidence:{first_segment:0}};
    const detail=structuralSignalDetail(signal,19.234);
    assert.equal(detail.title,signalName(type));assert.equal(detail.kind,'structure');assert.equal(detail.price,19.234);
    assert.equal(detail.date,signal.date);assert.equal(detail.confirmedDate,signal.confirmed_date);assert.equal(detail.message,signal.msg);
    assert.ok(detail.evidence.some(line=>line.includes('前置一类点线段：1')));
  }
})
test('legacy records do not invent confirmation or structural sources',()=>{
  const detail=structuralSignalDetail({type:'1buy',date:null,msg:'旧记录'},20);
  assert.equal(detail.confirmedDate,null);assert.equal(detail.date,null);
  assert.match(detail.source,/未提供/);assert.ok(!detail.evidence.some(line=>line.startsWith('规则：已确认')));
})
test('M1 keeps independent MACD source and original direction, never a structural type',()=>{
  for(const direction of ['up','down']){
    const detail=macdSignalDetail({type:'macd_wave',direction,status:'confirmed',curr_date:'2026-10-01',confirmed_date:'2026-10-02',msg:'MACD 原始依据',evidence:{}},23);
    assert.equal(detail.kind,'macd');assert.match(detail.title,new RegExp(direction==='up'?'卖出':'买入'));
    assert.match(detail.source,/标准波段/);assert.equal(detail.message,'MACD 原始依据');
  }
})
