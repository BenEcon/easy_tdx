import test from 'node:test'
import assert from 'node:assert/strict'
import { createMovingAverageSettings, MOVING_AVERAGE_PERIODS, movingAverageColor, movingAverageSelection } from '../src/moving-averages.ts'

test('all seven MA presets are available but only MA5 and MA10 start visible', () => {
  const settings = createMovingAverageSettings()
  assert.deepEqual(settings.map(item => item.period), [5, 10, 20, 30, 60, 120, 250])
  assert.deepEqual(settings.filter(item => item.enabled).map(item => item.period), [5, 10])
  assert.equal(settings.find(item => item.period === 250).enabled, false)
})

test('each chart session gets independent editable settings without changing presets', () => {
  const first = createMovingAverageSettings()
  first[6].enabled = true
  first[6].period = 200
  assert.deepEqual(createMovingAverageSettings()[6], { period: 250, enabled: false })
  assert.equal(MOVING_AVERAGE_PERIODS[6], 250)
})

test('MA presets retain the requested yellow, white, purple, green, cyan, orange, red palette', () => {
  assert.deepEqual(MOVING_AVERAGE_PERIODS.map(movingAverageColor), ['#ffff00', '#ffffff', '#da70d6', '#00ff00', '#00ffff', '#ff8c00', '#ff3030'])
})

test('legend retains every MA choice and explicit hidden states override stale chart selection', () => {
  const selection = movingAverageSelection([...MOVING_AVERAGE_PERIODS], [5, 10])
  assert.equal(Object.keys(selection).length, 7)
  assert.equal(selection.MA250, false)
  assert.equal(selection.MA5, true)
  assert.equal({ MA250: true, ...selection }.MA250, false)
  assert.equal(movingAverageSelection([5, 10, 200], [200]).MA200, true)
  assert.equal(movingAverageSelection([5, 10], []).MA5, false)
})
