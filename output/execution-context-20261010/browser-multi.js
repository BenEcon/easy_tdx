async(page)=>{
  const root='http://127.0.0.1:8768/api/v1',report={errors:[],dialogs:[],requests:[]},check=(ok,msg)=>{if(!ok)throw Error(msg)};
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('dialog',async d=>{report.dialogs.push(d.message());await d.accept()});
  await page.setViewportSize({width:1440,height:1000});
  const user=(await(await page.request.get(root+'/auth/me')).json()).user;
  const trade={cash:200000,commission:.0002,min_commission:1.23,stamp_tax:.0005,slippage:.002,execution:'next_close'};
  const items=['SZ:300450','SH:600699'].map(symbol=>({symbol,strategy:'ma_cross',strategy_label:'双均线',params:{fast:7,slow:31},category:'DAY',start_date:'2025-01-02',end_date:'2026-09-29'}));
  const seed=await page.request.post(root+'/strategies',{data:{name:'QA 多策略完整执行',kind:'multi',strategy:'multi',params:{},context:{items,cash:trade.cash,adjust:'QFQ'},trade_config:trade,tags:[],notes:''}});check(seed.status()===201,'创建失败');
  await page.request.patch(root+'/auth/me/preferences',{headers:{'X-Preferences-Owner':user.id},data:{preferences:{adjust_mode:'HFQ'}}});
  await page.reload();await page.getByRole('tab',{name:/组合/}).click();
  const card=page.locator('article').filter({has:page.getByRole('heading',{name:'QA 多策略完整执行',exact:true})});
  for(const mode of ['按原区间重跑','重跑到今天']){
    const submitted=page.waitForResponse(r=>r.url().includes('/multi-strategy/run/async'));
    const done=page.waitForResponse(async r=>r.url().includes('/backtest/tasks/')&&r.status()===200&&(await r.json()).status==='done');
    await card.getByRole('button',{name:mode,exact:true}).click();
    const response=await submitted,request=response.request().postDataJSON();report.requests.push(request);
    check(request.adjust==='QFQ','复权被全局设置覆盖');for(const [key,value]of Object.entries(trade))check(request[key]===value,key+' 丢失');
    if(mode==='按原区间重跑')check(request.items.every(v=>v.end_date==='2026-09-29'),'原日期未恢复');
    else check(request.items.every(v=>v.end_date==='2026-10-10'),'今天未按北京时间');
    const result=(await(await done).json()).result;check(result.total_performance.total_stocks===2,'丢失槽位');
    await page.getByRole('button',{name:'保存为组合',exact:true}).waitFor();
  }
  report.widths=[];
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000});await card.scrollIntoViewIfNeeded();
    await page.screenshot({path:`/Users/bowen/Documents/Python/Google/TDX-work/output/playwright/multi-context-${width}.png`});
    const actual=await page.evaluate(()=>document.documentElement.scrollWidth);check(actual<=width,'页面溢出');report.widths.push({width,actual});
  }
  check(report.dialogs.every(t=>t.includes('1.23')&&t.includes('QFQ')),'确认缺少成本说明');check(!report.errors.length,'页面错误');
  await page.evaluate(r=>window.__multiReport=r,report);
}
