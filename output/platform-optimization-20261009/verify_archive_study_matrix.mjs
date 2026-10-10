import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {archiveStudyPreview,studyOverviewIssue} from '../../web-ui/src/archive-study-preview.ts'
import {periodOverviewCells} from '../../web-ui/src/period-overview.ts'

const results=JSON.parse(readFileSync(0,'utf8'))
assert.equal(results.length,22)
let successful=0, sourceErrors=0
for(const item of results){
  const original=JSON.stringify(item),preview=archiveStudyPreview(item)
  assert.ok(preview,item.id)
  assert.equal(preview.entries.length,item.result.rows.length,item.id)
  assert.equal(preview.rows.length,item.result.rows.length,item.id)
  for(const [index,row] of item.result.rows.entries()){
    assert.equal(studyOverviewIssue(row),null,`${item.id}: ${studyOverviewIssue(row)}`)
    assert.equal(preview.entries[index].problem,null,item.id)
    if(row.error){sourceErrors++;assert.equal(preview.rows[index].error,row.error)}
    else {
      successful++
      assert.equal(preview.rows[index],row)
      assert.equal(periodOverviewCells(row).length,6)
      assert.ok(periodOverviewCells(row).every(column=>column.every(value=>typeof value==='string')))
    }
  }
  assert.equal(JSON.stringify(item),original,`${item.id}: original changed`)
}
assert.equal(successful,22)
assert.equal(sourceErrors,0)
console.log(JSON.stringify({cases:results.length,successful,sourceErrors,allRowsPreserved:true,allOverviewFieldsAccepted:true}))
