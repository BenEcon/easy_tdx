import test from 'node:test'
import assert from 'node:assert/strict'
import {matchesBreadthFilters,toggleBreadthFilter,matchesTrackingStatus} from '../src/tracking-filters.ts'
const selection=(metric,category='DAY')=>({category,metric})
const item=(category,direction,axis)=>({category,direction_observation:{strict:{direction}},pairs:{macd:{fast:axis,slow:axis}},divergences:[],buy_sell_points:[]})
const row={state:'done',study:{rows:[item('DAY','up',1),item('WEEK','down',-1)]}}
test('empty selections include every row, including incomplete results',()=>{
 assert.equal(matchesBreadthFilters(row,[]),true)
 assert.equal(matchesBreadthFilters({state:'error'},[]),true)
})
test('same period/column selections are OR, other columns and periods are AND',()=>{
 assert.equal(matchesBreadthFilters(row,[selection('penUp'),selection('penDown')]),true)
 assert.equal(matchesBreadthFilters(row,[selection('penUp'),selection('aboveZero')]),true)
 assert.equal(matchesBreadthFilters(row,[selection('penUp'),selection('belowZero')]),false)
 assert.equal(matchesBreadthFilters(row,[selection('penUp'),selection('penDown','WEEK')]),true)
 assert.equal(matchesBreadthFilters(row,[selection('penUp'),selection('penUp','WEEK')]),false)
})
test('total selection does not bypass other criteria; missing periods never count as neutral signals',()=>{
 assert.equal(matchesBreadthFilters(row,[selection('total'),selection('belowZero')]),false)
 assert.equal(matchesBreadthFilters(row,[selection('covered','MIN_5')]),false)
 assert.equal(matchesBreadthFilters({state:'error'},[selection('divergence')]),false)
})
test('toggle/removal preserves all other selections and never mutates input',()=>{
 const original=[selection('penUp')]
 const next=toggleBreadthFilter(original,selection('belowZero'))
 assert.deepEqual(original,[selection('penUp')]);assert.equal(next.length,2)
 assert.deepEqual(toggleBreadthFilter(next,selection('penUp')),[selection('belowZero')])
 assert.deepEqual(toggleBreadthFilter(original,selection('penUp')),[])
})
test('status selection uses OR with empty meaning all; can combine with breadth',()=>{
 for(const state of ['pending','running','done','error','cancelled'])assert.equal(matchesTrackingStatus({state},[]),true)
 assert.equal(matchesTrackingStatus(row,['done','error']),true)
 assert.equal(matchesTrackingStatus({state:'error'},['done','error']),true)
 assert.equal(matchesTrackingStatus(row,['error','cancelled']),false)
 assert.equal(matchesTrackingStatus(row,['done'])&&matchesBreadthFilters(row,[selection('penDown')]),false)
})
