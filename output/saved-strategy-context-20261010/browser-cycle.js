async (page) => {
  const base='http://127.0.0.1:8768', id=new URL(page.url()).searchParams.get('savedStrategyId')
  const original=await(await page.request.get(`${base}/api/v1/strategies/${id}`)).json()
  const owner=(await(await page.request.get(`${base}/api/v1/auth/me`)).json()).user.id
  const requests=[], errors=[]
  page.on('pageerror',e=>errors.push(String(e)))
  page.on('request',r=>{if(/\/bars\/range|\/backtest\/run|\/strategies/.test(r.url()))requests.push({url:r.url(),method:r.method(),headers:r.headers(),body:r.postDataJSON()})})
  const stable=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.keys(x).sort().map(k=>[k,x[k]])):x)
  function equal(a,b,label){if(stable(a)!==stable(b))throw Error(`${label}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`)}
  const response=page.waitForResponse(r=>r.url().endsWith('/backtest/run'))
  await page.getByRole('button',{name:'开始回测',exact:true}).click()
  const res=await response
  if(res.status()!==200)throw Error(await res.text())
  const result=await res.json()
  const run=requests.find(r=>r.url.endsWith('/backtest/run'))
  equal(run.body.params,original.params,'params')
  for(const [key,value]of Object.entries(original.trade_config))equal(run.body[key],value,key)
  equal(run.headers['x-query-origin'],'user','manual origin')
  const bars=requests.find(r=>r.url.includes('/bars/range'))
  const query=new URL(bars.url).searchParams
  for(const key of ['category','adjust','start_date','end_date'])equal(query.get(key),original.context[key],key)
  await page.getByRole('button',{name:'保存策略',exact:true}).click()
  const savedName=`QA 再保存一致性 ${Date.now()}`
  await page.getByPlaceholder('给这个策略起个名').fill(savedName)
  const saveResponse=page.waitForResponse(r=>r.url().endsWith('/strategies')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'保存',exact:true}).click()
  const savedResponse=await saveResponse
  if(savedResponse.status()!==201)throw Error(await savedResponse.text())
  const saved=await savedResponse.json()
  for(const key of ['context','params','trade_config'])equal(saved[key],original[key],key)
  equal(saved.snapshot.total_return,result.performance.total_return,'performance precision')
  equal(requests.find(r=>r.method==='POST'&&r.url.endsWith('/strategies')).headers['x-strategy-owner'],owner,'save owner')
  const afterSaveRuns=requests.filter(r=>r.url.endsWith('/backtest/run')).length
  await page.getByRole('link',{name:'策略库',exact:true}).click()
  const row=page.getByRole('article').filter({has:page.getByRole('heading',{name:savedName,exact:true})})
  await row.getByRole('button',{name:'载入',exact:true}).click()
  await page.getByRole('heading',{name:`已载入：${savedName}`,exact:true}).waitFor()
  for(const [label,value]of Object.entries({'快线周期':'7','慢线周期':'31','初始资金':'200000','佣金率':'0.0002','最低佣金':'1.23','印花税率':'0.0005','滑点':'0.002'}))equal(await page.getByRole('textbox',{name:label,exact:true}).inputValue(),value,label)
  equal(new URL(page.url()).searchParams.get('savedStrategyId'),saved.id,'reopened id')
  equal(requests.filter(r=>r.url.endsWith('/backtest/run')).length,afterSaveRuns,'no auto run')
  const widths=[]
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000})
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)
    if(overflow)throw Error(`Overflow at ${width}`)
    widths.push({width,overflow})
    await page.screenshot({path:`output/playwright/saved-strategy-${width}.png`,fullPage:true})
  }
  await page.evaluate(report=>window.__savedQaReport=report,{id:saved.id,trades:result.trades.length,barCount:run.body.ohlcv.length,manualRequests:requests.filter(r=>/\/bars\/range|\/backtest\/run/.test(r.url)).length,matchingCosts:true,reopenNoRun:true,widths,errors})
}
