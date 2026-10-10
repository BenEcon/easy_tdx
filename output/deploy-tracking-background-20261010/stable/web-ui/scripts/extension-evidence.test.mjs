import test from 'node:test'
import assert from 'node:assert/strict'
import { admissionReason, admissionWitness } from '../src/extension-evidence.ts'

test('membership labels distinguish source confirmation from later admission', () => {
  assert.equal(admissionReason('seed_formation'), '三段共同形成中枢')
  assert.equal(admissionReason('extension'), '中枢延伸纳入')
  assert.match(admissionReason('failed_departure_return'), /回试确认后纳入/)
  assert.equal(admissionReason('unexpected'), '接纳原因未提供')
})

test('admission witness distinguishes confirmation dependency from geometric membership', () => {
  assert.equal(admissionWitness({admission_segment_index: 9}, [6, 7, 8]),
    '接纳依据：线段 10（本分组外，仅作确认依据）')
  assert.equal(admissionWitness({admission_segment_index: 2}, [0, 1, 2]), '接纳依据：线段 3')
  assert.equal(admissionWitness({admission_segment_index: 0}, [0, 1, 2]), '接纳依据：线段 1')
  assert.equal(admissionWitness({admission_segment_index: 29}, [26, 27, 28]),
    '接纳依据：线段 30（本分组外，仅作确认依据）')
})

test('old or malformed evidence never invents an admission witness', () => {
  for (const value of [undefined, null, -1, 1.5, NaN, Infinity, true, '9']) {
    assert.equal(admissionWitness({admission_segment_index: value}, [6, 7, 8]), '接纳依据线段未提供')
  }
})
