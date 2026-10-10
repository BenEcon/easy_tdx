import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync,readdirSync } from 'node:fs'
import { archiveTime,validateArchiveBars } from '../src/archive-data-validation.ts'

test('archive calendar validation rejects normalized impossible dates and illegal clock/offset values',()=>{
  for(const value of ['2026-02-29 00:00:00','2026-02-30','2026-04-31','2026-00-02','2026-13-01','2026-01-01 24:00:00','2026-01-01 12:60:00','2026-01-01T12:00:00+01:60','2026-01-01T12:00:00+24:00','2026-01-01junk',null,7])assert.equal(archiveTime(value),null,String(value))
  assert.notEqual(archiveTime('2024-02-29 23:59:59.123456'),null)
  assert.equal(archiveTime('2026-10-09 15:00:00'),archiveTime('2026-10-09T07:00:00Z'))
  assert.equal(archiveTime('2026-10-09'),archiveTime('2026-10-08T16:00:00Z'))
  assert.equal(archiveTime('2026-10-09',true),null)
})

test('bar validation compares actual instants, retains raw strings, rejects equal instants and malformed volume',()=>{
  const bar={datetime:'2026-10-09 09:30:00',open:1,close:2,low:1,high:3,vol:0,amount:0,is_closed:false}
  const valid=[bar,{...bar,datetime:'2026-10-09T02:00:00Z'}],before=JSON.stringify(valid)
  validateArchiveBars(valid);assert.equal(JSON.stringify(valid),before)
  for(const change of [v=>v.datetime='2026-10-09T01:30:00Z',v=>v.datetime='2026-10-09T01:29:00Z',v=>v.vol='0',v=>v.amount=true,v=>v.is_closed='false']){
    const next=structuredClone(valid[1]);change(next);assert.throws(()=>validateArchiveBars([bar,next]))
  }
})

test('existing frozen matrix bar sources remain readable without mutation',()=>{
  const root=new URL('../../tests/fixtures/market_matrix/',import.meta.url)
  let cases=0,bars=0
  for(const file of readdirSync(root).filter(n=>n.endsWith('.json'))){
    const data=JSON.parse(readFileSync(new URL(file,root),'utf8'))
    if(!Array.isArray(data.bars))continue
    const original=JSON.stringify(data.bars)
    validateArchiveBars(data.bars);assert.equal(JSON.stringify(data.bars),original,file)
    cases++;bars+=data.bars.length
  }
  assert.ok(cases>=10);assert.ok(bars>1000)
})
