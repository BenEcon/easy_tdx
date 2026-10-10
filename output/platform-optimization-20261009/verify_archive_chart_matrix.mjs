import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {validateArchiveChartResult} from '../../web-ui/src/archive-chart-validation.ts'
import {segmentEvidence,centreEvidence} from '../../web-ui/src/structure-evidence.ts'
import {divergenceEvidence,signalEvidence,waveDiagnosticLines,waveComparisonLines} from '../../web-ui/src/divergence-evidence.ts'
import {visibleDivergences,macdPrompts,divergenceMarker} from '../../web-ui/src/divergence-marker.ts'
import {nextPenPreview} from '../../web-ui/src/structure-preview.ts'

const cases=JSON.parse(readFileSync(0,'utf8')),counts={cases:0,pens:0,segments:0,centres:0,divergences:0,signals:0,diagnostics:0,comparisons:0}
assert.equal(cases.length,22)
const readable=lines=>assert.ok(lines.every(line=>typeof line==='string'&&!line.includes('NaN')&&!line.includes('[object Object]')))
for(const item of cases){
  const result=item.result,original=JSON.stringify(item)
  validateArchiveChartResult(result,item.id)
  for(const segment of [...result.xds,...(result.unfinished_xd?[result.unfinished_xd]:[])])readable(segmentEvidence(segment))
  for(const centre of [...result.zss,...(result.structural_centres??[])])readable(centreEvidence(centre))
  for(const divergence of result.bcs)readable(divergenceEvidence(divergence))
  for(const signal of result.mmds)readable(signalEvidence(signal))
  for(const diagnostic of result.wave_diagnostics??[]){
    readable(waveDiagnosticLines(diagnostic))
    for(const comparison of diagnostic.comparisons??[]){readable(waveComparisonLines(comparison));counts.comparisons++}
  }
  for(const divergence of visibleDivergences(result.bcs,true))assert.ok(divergenceMarker(divergence,true))
  macdPrompts(result.bcs);nextPenPreview(item.bars,result.bis)
  assert.equal(JSON.stringify(item),original,item.id)
  counts.cases++;counts.pens+=result.bis.length;counts.segments+=result.xds.length
  counts.centres+=(result.structural_centres??[]).length;counts.divergences+=result.bcs.length
  counts.signals+=result.mmds.length;counts.diagnostics+=(result.wave_diagnostics??[]).length
}
console.log(JSON.stringify({...counts,originalsUnchanged:true,allCurrentInspectorEvidenceReadable:true}))
