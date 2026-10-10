import test from 'node:test'
import assert from 'node:assert/strict'
import { evidenceReadingRows } from '../src/evidence-reading.ts'

test('display fields retain all text including dates, provenance, and secondary colons',()=>{
  const lines=['确认方式：特殊包含（第 71、78 课）：分界两侧不合并','极值端点：2026-07-10 10:30:00；确认时间：2026-07-15 15:00:00','特征元素 1：19.00–23.00；来源笔 1、3；高点来自笔 3，低点来自笔 1','确认所需最后一笔：8（可位于线段端点之后）'];
  const rows=evidenceReadingRows(lines);
  assert.equal(rows[0].label,'确认方式');
  assert.deepEqual(rows.map(row=>row.label===null?row.text:`${row.label}：${row.text}`),lines);
});
test('narrative, missing evidence, and timestamp headings remain whole',()=>{
  const lines=['此结果未提供特征序列依据，请重新分析。','2026-07-15 15:00:00 · 与中枢 3：外围向上分离','关系按已纳入线段计算；退出不代表趋势结束。',''];
  assert.deepEqual(evidenceReadingRows(lines),lines.map(text=>({label:null,text})));
  assert.deepEqual(evidenceReadingRows([]),[]);
});
