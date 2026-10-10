import fs from 'node:fs'
import assert from 'node:assert/strict'
import { compareArchiveEvents } from '../../web-ui/src/archive-event-comparison.ts'

const rows=JSON.parse(fs.readFileSync(new URL('../platform-optimization-20261009/archive-chart-real-output.json',import.meta.url),'utf8'))
assert.equal(rows.length,22)
for(const row of rows){
  const before=row.result,after=structuredClone(before)
  for(const key of ['bcs','mmds','wave_diagnostics'])after[key]?.reverse()
  for(const record of after.wave_diagnostics??[]){record.checks?.reverse();record.comparisons?.reverse();record.rejections?.reverse()}
  const start=performance.now(),report=compareArchiveEvents(before,after)
  assert.equal(report.applicable,true,row.id)
  assert.deepEqual([report.counts.added,report.counts.removed,report.counts.changed,report.counts.unresolved],[0,0,0,0],row.id)
  assert.equal(report.counts.same,['bcs','mmds','wave_diagnostics'].reduce((sum,key)=>sum+(before[key]?.length??0),0),row.id)
  console.log(JSON.stringify({id:row.id,counts:report.counts,ms:Math.round(performance.now()-start),coverage:report.coverage}))
}
