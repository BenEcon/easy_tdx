import test from 'node:test'
import assert from 'node:assert/strict'
import { radarCacheKey, readRadarCache, radarReviewQuery, readRadarReview, reviewTime, sameReviewInput, sameReviewStrategy, snapshotForReview } from '../src/radar-review.ts'

const metadata = { source:'MAC', actual_adjust:'QFQ', requested_adjust:'QFQ', category:'MIN_30', observed_at:'2026-10-09 15:00:00', last_closed_at:'2026-09-30 14:30:00', data_fingerprint:'a'.repeat(64) }
const row = { strategy_id:'one',strategy_name:'缠论',strategy_label:'买卖点',kind:'single',strategy:'chanlun_mmd',params:{buy_types:'1,2',n:5},symbol:'SZ:300750',category:'MIN_30',metadata,latest_signal:'BUY',signal_date:'2026-09-30 14:30',recent_signals:[{date:'2026-09-30 14:30',direction:'BUY'}],position:'flat',last_close:10,last_bar_date:'2026-09-30 14:30',error:null }
const query = radarReviewQuery(row, 'NONE')
const review = readRadarReview(query).value

test('radar review captures row adjustment, exact minute, strategy and original cutoff', () => {
  assert.equal(query.adjust,'QFQ'); assert.equal(query.market,'SZ')
  assert.equal(review.asOf,'2026-09-30 14:30:00')
  assert.equal(review.signalDate,'2026-09-30 14:30:00')
  assert.deepEqual(review.params,row.params)
  assert.equal(sameReviewInput(review,'300750','MIN_30','QFQ'),true)
  for (const args of [['600699','MIN_30','QFQ'],['300750','DAY','QFQ'],['300750','MIN_30','NONE']]) assert.equal(sameReviewInput(review,...args),false)
  assert.equal(sameReviewStrategy(review,'chanlun_mmd',{n:5,buy_types:'1,2'}),true)
  assert.equal(sameReviewStrategy(review,'chanlun_mmd',{n:6,buy_types:'1,2'}),false)
  assert.equal(sameReviewStrategy(review,'other',row.params),false)
  const other = radarReviewQuery(row,'QFQ',{date:'2026-09-29 10:00',direction:'SELL'})
  assert.equal(other.signalDate,'2026-09-29 10:00'); assert.equal(other.scanAsOf,query.scanAsOf)
})
test('invalid or legacy reviews fail explicitly without guessing data or adjustment', () => {
  for (const patch of [{adjust:''},{scanAsOf:''},{market:'SH'},{symbol:'../file'},{category:'YEAR'},{signalDate:'2026-10-01'},{params:'[]'},{params:'{"x":null}'},{params:'{"x":1e999}'},{params:'bad'},{params:['{}']},{signal:'unknown'},{scanFingerprint:[]},{scanFingerprint:'abc'},{strategy:''},{scanAsOf:['2026-09-30']}]) {
    const parsed = readRadarReview({...query,...patch}); assert.equal(parsed.value,null,JSON.stringify(patch)); assert.ok(parsed.error)
  }
  assert.deepEqual(readRadarReview({}),{value:null,error:''})
  assert.throws(()=>radarReviewQuery({...row,metadata:undefined},'QFQ'),/截止/)
})
test('exchange-local dates validate without browser timezone conversion', () => {
  assert.equal(reviewTime('2026-09-30T14:30'),'2026-09-30 14:30:00')
  assert.equal(reviewTime('2024-02-29'),'2024-02-29 00:00:00')
  for (const raw of ['2026-02-29','2026-13-01','2026-09-30 24:00','2026-09-30T14:30Z','2026-09-30 14:30+08:00','2026-09-30 12:60']) assert.equal(reviewTime(raw),'')
})
const bars = ['14:00','14:30','15:00'].map(time => ({datetime:`2026-09-30 ${time}:00`,period_end:`2026-09-30 ${time}:00`,is_closed:true,close:1}))
test('review excludes future and unclosed bars, resets derived fingerprint and reports actual range without mutating source', () => {
  const source = {metadata:{...metadata,range_end:'2026-10-09',excluded_open_count:2},bars}
  const before = JSON.stringify(source)
  const clipped = snapshotForReview(source,review)
  assert.equal(clipped.bars.length,2)
  assert.equal(clipped.metadata.data_fingerprint,undefined)
  assert.equal(clipped.metadata.source_fingerprint,metadata.data_fingerprint)
  assert.equal(clipped.metadata.range_end,'2026-09-30 14:30:00')
  assert.equal(clipped.metadata.excluded_open_count,2) // future closed bars are not mislabeled as unclosed
  assert.match(clipped.metadata.consistency_note,/不代表重现原扫描/)
  assert.equal(JSON.stringify(source),before)
  assert.equal(snapshotForReview({...source,bars:bars.slice(0,2)},review).metadata.data_fingerprint,metadata.data_fingerprint)
  assert.equal(snapshotForReview({...source,bars:bars.map((bar,i)=>({...bar,is_closed:i===0}))},review).bars.length,1)
  assert.throws(()=>snapshotForReview({...source,metadata:{...metadata,actual_adjust:'NONE'}},review),/复权/)
  assert.throws(()=>snapshotForReview({...source,metadata:{...metadata,requested_adjust:'NONE'}},review),/复权/)
  assert.throws(()=>snapshotForReview({...source,metadata:{...metadata,category:'DAY'}},review),/周期/)
  assert.throws(()=>snapshotForReview({...source,bars:[bars[2]]},review),/未覆盖/)
})
test('radar cache is owner scoped and malformed/legacy records never enter the UI', () => {
  const result = {rows:[row],total:1,buy_count:1,sell_count:0,error_count:0,elapsed:1}
  const cache = {schema:'radar-cache-v2',owner:'a',result,scannedAt:'now',windowBars:5,adjust:'QFQ'}
  assert.notEqual(radarCacheKey('a'),radarCacheKey('b'))
  assert.deepEqual(readRadarCache(JSON.stringify(cache),'a'),cache)
  assert.equal(readRadarCache(JSON.stringify(cache),'b'),null)
  assert.equal(readRadarCache(JSON.stringify(result),'a'),null)
  for (const patch of [{recent_signals:null},{recent_signals:[null]},{params:null},{symbol:55},{metadata:[]},{error:3},{last_close:'10'},{latest_signal:'WRONG'},{position:[]},{signal_date:[]},{last_bar_date:55}]) assert.equal(readRadarCache(JSON.stringify({...cache,result:{...result,rows:[{...row,...patch}]}}),'a'),null)
  assert.equal(readRadarCache('invalid','a'),null)
  for(const patch of [{total:2},{total:1.5},{buy_count:0},{sell_count:1},{error_count:1}])assert.equal(readRadarCache(JSON.stringify({...cache,result:{...result,...patch}}),'a'),null)
})
