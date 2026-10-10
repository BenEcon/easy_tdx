async page => {
  const created=await page.evaluate(async()=>{
    const owner=(await (await fetch('/api/v1/auth/me')).json()).user.id
    const post=async(url,body,method='POST')=>{const response=await fetch('/api/v1/'+url,{method,headers:{'Content-Type':'application/json','X-Research-Owner':owner},body:JSON.stringify(body)});if(!response.ok)throw Error(response.status+' '+await response.text());return response.json()}
    const bars=Array.from({length:160},(_,i)=>{const p=20+Math.sin(i/7)*3+i/200;return{datetime:new Date(Date.UTC(2026,0,1+i)).toISOString().slice(0,10)+' 00:00:00',open:p,close:p+.2,high:p+.5,low:p-.5,vol:100+i,amount:2000+i,is_closed:true}})
    const indicators=[{type:'volume',params:{}},{type:'macd',params:{SHORT:12,LONG:26,M:9}},{type:'rsi',params:{N:6}},{type:'boll',params:{N:20,P:2}}]
    const settings={averages:[{period:5,enabled:true},{period:17,enabled:false}],indicators}
    const computed=await post('chanlun/archive-recompute',{request_id:crypto.randomUUID(),kind:'chart',chart:{code:'stock:SZ:300750',category:'DAY',bars,visible_count:bars.length},chart_indicators:settings})
    const outputs=[['VOL','MAVOL5','MAVOL10'],['MACD_DIF','MACD_DEA','MACD_HIST'],['RSI'],['BOLL_UPPER','BOLL_MID','BOLL_LOWER']]
    const names=[['成交量','MAVOL5','MAVOL10'],['DIF','DEA','HIST'],['RSI'],['UPPER','MID','LOWER']]
    const frozen={schema:1,source:'captured-chart-series',dates:bars.map(row=>row.datetime),averages:computed.indicator_data.averages,indicators:indicators.map((item,i)=>({...item,label:['成交量','MACD','RSI','BOLL'][i],placement:item.type==='boll'?'overlay':'panel',guideLines:[],series:outputs[i].map((key,j)=>({name:names[i][j],type:key==='VOL'||key==='MACD_HIST'?'bar':'line',symbol:'none',color:j===0?'#ffff00':'#ffffff',values:computed.indicator_data.indicators[i].rows.map(row=>row[key])}))}))}
    // Deliberate old-version artifacts: a warmup zero and a tiny numerical difference.
    frozen.indicators[3].series[0].values[0]=0
    frozen.averages[0].values[20]+=1e-9
    const payload={schema:1,id:'synthetic-indicators',name:'完整指标 QA',note:'明确合成行情',title:'300750 QA',cutoff:'2026-09-30 15:00:00',savedAt:'2026-10-09T08:00:00Z',frontendVersion:'old-QA',ruleVersions:[],target:{kind:'stock',market:'SZ',code:'300750'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},charts:[{category:'DAY',bars,metadata:{actual_adjust:'QFQ',bar_time:'start',observed_at:'2026-09-30 15:00:00'},result:computed.result,frozenIndicators:frozen}]}
    const old=await post('research/archives/'+crypto.randomUUID(),{kind:'chart',name:payload.name,note:payload.note,payload},'PUT')
    return {id:old.id,digest:old.digest}
  })
  const requests=[],errors=[]
  page.on('request',r=>{if(/\/api\/v1\/(chanlun|bars|indicator)/.test(r.url()))requests.push({url:r.url(),origin:r.headers()['x-query-origin']})})
  page.on('pageerror',e=>errors.push(e.message))
  await page.getByText('账户云存档',{exact:true}).click()
  await page.getByRole('listitem').filter({has:page.getByText('完整指标 QA',{exact:true})}).getByRole('button',{name:'查看原档',exact:true}).click()
  await page.locator('.archive-recompute > summary').click()
  await page.getByRole('button',{name:'检查重算条件',exact:true}).click()
  if(requests.length)throw Error('preview computed '+JSON.stringify(requests))
  await page.getByRole('button',{name:'确认按当前版本重算',exact:true}).click()
  await page.getByText('所选原档的可重算内容已计算完成；原档未覆盖。请核对差异后决定是否保存新副本。',{exact:true}).waitFor()
  const diff=await page.locator('.diff-scroll').innerText()
  if(!diff.includes('frozenIndicators')||!diff.includes('null'))throw Error('missing warmup diff')
  await page.getByRole('button',{name:'另存重算新副本',exact:true}).click()
  await page.getByRole('button',{name:'新副本已保存',exact:true}).waitFor()
  const base='http://127.0.0.1:8768/api/v1/research/archives'
  const archives=await (await page.request.get(base)).json()
  const old=archives.items.find(row=>row.id===created.id),fresh=archives.items.find(row=>row.name==='完整指标 QA · 重算')
  if(old.digest!==created.digest||!fresh)throw Error('original changed or save failed')
  const newRecord=await (await page.request.get(base+'/'+fresh.id)).json()
  const frozen=newRecord.payload.charts[0].frozenIndicators
  if(frozen.indicators.length!==4||frozen.averages.length!==2||frozen.indicators[3].series[0].values[0]!==null)throw Error('incomplete frozen copy')
  if(requests.length!==1||requests[0].origin!=='user')throw Error('unexpected automatic/duplicate compute')
  const layouts=[]
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000});await page.locator('.archive-recompute').scrollIntoViewIfNeeded()
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
    const size=await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth}));if(size.document>width)throw Error('overflow');layouts.push(size)
    await page.locator('.archive-recompute').screenshot({path:'output/playwright/archive-indicators-'+width+'.png'})
  }
  await page.reload();await page.getByText('账户云存档',{exact:true}).click()
  await page.getByRole('listitem').filter({has:page.getByText('完整指标 QA · 重算',{exact:true})}).getByRole('button',{name:'查看原档',exact:true}).click()
  await page.getByRole('dialog',{name:'云端研究原档'}).waitFor()
  if(requests.length!==1||errors.length)throw Error('reopened copy computed or crashed '+JSON.stringify({requests,errors}))
  return {originalUnchanged:true,averages:frozen.averages.map(row=>row.period),indicators:frozen.indicators.map(row=>({type:row.type,params:row.params})),diff,requests,layouts,errors}
}
