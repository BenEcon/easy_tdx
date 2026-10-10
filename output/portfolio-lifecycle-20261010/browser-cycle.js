async (page) => {
  const root='http://127.0.0.1:8768/api/v1',report={requests:[],errors:[]};
  page.on('pageerror',e=>report.errors.push(String(e)));
  page.on('request',r=>{if(r.url().includes('/backtest/portfolio/run/async')||r.url().includes('/backtest/tasks/'))report.requests.push({url:r.url(),method:r.method(),origin:r.headers()['x-query-origin']??null,owner:r.headers()['x-task-owner']??null,body:r.postDataJSON()});});
  const check=(yes,message)=>{if(!yes)throw Error(message)};
  await page.getByRole('button',{name:'载入',exact:true}).click();
  await page.getByRole('heading',{name:'已载入：QA 组合完整配置',exact:true}).waitFor();
  check(report.requests.length===0,'载入不应自动回测');
  for(const [label,value] of Object.entries({'组合总资金':'200000','佣金率':'0.0002','最低佣金':'1.23','印花税率':'0.0005','滑点':'0.002','快线周期':'7','慢线周期':'31'}))check(await page.getByRole('textbox',{name:label,exact:true}).inputValue()===value,label+' 恢复错误');
  const sourceId=new URL(page.url()).searchParams.get('savedStrategyId');
  const source=await (await page.request.get(root+'/strategies/'+sourceId)).json();
  const terminal=page.waitForResponse(async r=>r.url().includes('/backtest/tasks/')&&r.status()===200&&(await r.json()).status==='done');
  await page.getByRole('button',{name:'开始组合回测',exact:true}).click();
  const done=await (await terminal).json();
  await page.getByRole('button',{name:'保存策略',exact:true}).waitFor();
  await page.getByRole('button',{name:'保存策略',exact:true}).click();
  await page.getByPlaceholder('给这个组合策略起个名').fill('QA 完整组合往返');
  const saved=page.waitForResponse(r=>r.url()===root+'/strategies'&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存',exact:true}).click();
  const record=await (await saved).json();
  const canonical=x=>JSON.stringify(x,(_k,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort()):v);
  for(const key of ['context','params','trade_config'])check(canonical(source[key])===canonical(record[key]),key+' 保存不一致');
  check(record.snapshot.total_return===done.result.total_performance.total_return,'绩效不是实际结果');
  report.taskId=done.task_id;report.recordId=record.id;report.sourceId=sourceId;report.performance=done.result.total_performance;report.stocks=done.result.results?.length;
  check(report.requests.filter(r=>r.method==='POST').every(r=>r.origin==='user'&&r.owner),'主动提交来源/归属缺失');
  check(report.requests.filter(r=>r.method==='GET').every(r=>r.origin!=='user'&&r.owner),'轮询误记主动查询');
  await page.getByRole('link',{name:'策略库',exact:true}).click();
  await page.getByRole('tab',{name:/组合/}).click();
  await page.locator('article').filter({has:page.getByRole('heading',{name:'QA 完整组合往返',exact:true})}).getByRole('button',{name:'载入',exact:true}).click();
  await page.getByRole('heading',{name:'已载入：QA 完整组合往返',exact:true}).waitFor();
  check(new URL(page.url()).searchParams.get('savedStrategyId')===record.id,'重开不是原 ID');
  check(report.requests.filter(r=>r.method==='POST').length===1,'重开意外自动运行');
  check(await page.getByRole('textbox',{name:'最低佣金',exact:true}).inputValue()==='1.23','重开成本丢失');
  report.widths=[];
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000});
    await page.getByRole('heading',{name:'已载入：QA 完整组合往返',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:`output/playwright/portfolio-lifecycle-${width}.png`});
    const actual=await page.evaluate(()=>document.documentElement.scrollWidth);
    report.widths.push({width,actual});check(actual<=width,'页面溢出');
  }
  check(report.errors.length===0,'浏览器错误');
  await page.evaluate(r=>window.__portfolioReport=r,report);
  console.log(JSON.stringify(report));
}
