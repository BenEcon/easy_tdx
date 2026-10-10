import test from 'node:test'
import assert from 'node:assert/strict'
import { escapeChartText } from '../src/chart-text.ts'
test('archive tooltip labels and evidence remain text, not active HTML',()=>{
  assert.equal(escapeChartText('<img src=x onerror="alert(1)"> & \'x\''),'&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;x&#39;')
  assert.equal(escapeChartText('成交量 · MAVOL5'),'成交量 · MAVOL5')
  assert.equal(escapeChartText(undefined),'')
})
