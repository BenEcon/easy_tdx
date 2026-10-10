async (page) => {
  const savedQa = { requests: [], errors: [] }
  page.on('pageerror', e => savedQa.errors.push(String(e)))
  page.on('request', r => { if (/\/bars\/range|\/backtest\/run|\/strategies/.test(r.url())) savedQa.requests.push({url:r.url(),method:r.method(),headers:r.headers(),body:r.postDataJSON()}) })
  await page.route('**/api/v1/quotes', r => r.fulfill({json:{data:[{code:'300450',name:'先导智能'}]}}))
  await page.route('**/api/v1/mac/symbol-info?**', r => r.fulfill({json:{data:[{code:'300450',name:'先导智能'}]}}))
  const login=await page.request.post('http://127.0.0.1:8768/api/v1/auth/login',{data:{username:'saved-qa',password:'Local-saved-QA-only-2026!'}})
  if(login.status()!==200)throw Error(await login.text())
  const auth = await (await page.request.get('http://127.0.0.1:8768/api/v1/auth/me')).json()
  savedQa.owner = auth.user.id
  savedQa.payload={name:'QA 完整配置闭环',kind:'single',strategy:'ma_cross',strategy_label:'均线交叉',params:{fast:7,slow:31},context:{symbol:'SZ:300450',category:'DAY',adjust:'QFQ',start_date:'2025-01-02',end_date:'2026-09-30'},trade_config:{cash:200000,commission:.0002,min_commission:1.23,stamp_tax:.0005,slippage:.002,execution:'next_close'},tags:[],notes:'本地冻结行情验收'}
  const created = await page.request.post('http://127.0.0.1:8768/api/v1/strategies',{headers:{'X-Strategy-Owner':savedQa.owner},data:savedQa.payload})
  if(created.status()!==201)throw Error(await created.text())
  savedQa.id=(await created.json()).id
  await page.goto('http://127.0.0.1:8768/strategies')
  await page.getByText('QA 完整配置闭环',{exact:true}).waitFor()
  await page.getByRole('article').filter({has:page.getByRole('heading',{name:'QA 完整配置闭环',exact:true})}).getByRole('button',{name:'载入',exact:true}).click()
  await page.getByRole('heading',{name:'已载入：QA 完整配置闭环',exact:true}).waitFor()
  if(savedQa.requests.some(r=>/\/bars\/range|\/backtest\/run/.test(r.url)))throw Error('Automatic computation on load')
  await page.evaluate(value=>window.__qaInitialLoad=value,{automaticQueries:0,id:savedQa.id})
}
