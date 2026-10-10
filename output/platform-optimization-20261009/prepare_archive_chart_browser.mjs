import {readFileSync} from 'node:fs'
const item=JSON.parse(readFileSync(0,'utf8')).find(item=>item.id==='stock-300750-day-20261009')
if(!item)throw Error('missing hash-checked case')
const payload={schema:1,title:'QA 真实冻结行情 · 300750',cutoff:'2026-10-09 15:00:00',target:{kind:'stock',code:'300750',market:'SZ'},
  preferences:{},layers:{bis:true,xds:true,zss:true,bcs:true,mmds:true,consolidations:true,nextPen:true},history:true,ruleVersions:[],frontendVersion:'QA-original-export',
  charts:[{category:'DAY',metadata:{actual_adjust:'QFQ',observed_at:'2026-10-09 15:00:00'},bars:item.bars,result:item.result}]}
if(process.argv[2]==='bad-related'){
  if(!item.result.bcs.length)throw Error('case must exercise an actual divergence')
  payload.title='QA 故障注入 · 关联事件字段损坏'
  item.result.bcs[0].related_events=[{signal_date:42,detected_date:'2026-10-09 15:00',status:'candidate'}]
}
if(process.argv[2]==='bad-feature'){
  if(!item.result.unfinished_xd)throw Error('case must exercise an unfinished segment')
  payload.title='QA 故障注入 · 线段特征字段损坏'
  item.result.unfinished_xd.evidence.features=[{low:'wrong',high:20,pen_indices:[1],high_pen:1,low_pen:1}]
}
console.log(JSON.stringify({kind:'chart',name:payload.title,note:'使用原始哈希核验的冻结案例；不代表当前实时行情。',payload}))
