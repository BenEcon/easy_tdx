async page => {
  const base='http://127.0.0.1:8768',requests=[],errors=[],reports=[];
  const check=(v,m)=>{if(!v)throw Error(m)};
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v);
  const listen=r=>requests.push({path:new URL(r.url()).pathname,method:r.method(),origin:r.headers()['x-query-origin']});
  const error=e=>errors.push(e.message);
  page.on('request',listen);page.on('pageerror',error);
  await page.route('**/api/v1/mac/quote-list?**',r=>r.fulfill({json:{data:[{code:'300750',market:0,name:'宁德时代',price:350},{code:'000001',market:1,name:'上证指数',price:3800}]}}));
  await page.route('**/api/v1/board-mac/list?**',r=>r.fulfill({json:{data:[{code:'881218',name:'汽车零部件',market:1,board_type:0}]}}));
  // Synthetic membership tests identity propagation, not actual industry membership.
  await page.route('**/api/v1/board-mac/members?**',r=>r.fulfill({json:{data:[{code:'300750',name:'宁德时代',market:0,close:350}]}}));
  await page.route('**/api/v1/board-mac/summary?**',r=>r.fulfill({json:{data:{member_count:1}}}));
  try {
    await page.setViewportSize({width:1440,height:1000});
    for(const [source,kind,code,label] of [['market','index','000001','上证指数'],['boards','board','881218','汽车零部件'],['boards','stock','300750','宁德时代']]) {
      const begin=requests.length;await page.goto(base+'/'+source);
      await page.getByRole('cell',{name:label,exact:true}).click();
      const bar=source==='market'?page.getByRole('region',{name:'继续研究选中标的'}):page.locator(kind==='board'?'.board-pane':'.member-pane').getByRole('region',{name:'继续研究选中标的'});
      await bar.getByRole('combobox',{name:'继续研究周期'}).click();await page.getByRole('option',{name:'日线',exact:true}).click();
      if(kind==='stock'){await bar.getByRole('combobox',{name:'继续研究复权'}).click();await page.getByRole('option',{name:/前复权/}).click()}
      await bar.getByRole('link',{name:'缠论结构',exact:true}).click();await page.getByLabel('研究入口参数').waitFor();
      check(!requests.slice(begin).some(r=>r.path==='/api/v1/bars'||r.path==='/api/v1/bars/research'||r.path==='/api/v1/chanlun/replay'),'entry automatically computed');
      const calculation=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/chanlun/replay');
      await page.getByRole('button',{name:'开始分析',exact:true}).click();const response=await calculation;
      check(response.ok(),await response.text());const result=await response.json();
      await page.getByRole('navigation',{name:'缠论工作区'}).getByRole('button',{name:/研究/}).click();
      const workspace=page.getByRole('region',{name:'研究工作区'});
      await workspace.locator('.workspace-tools > summary').click();
      const cloud=workspace.locator(':scope > .cloud-archives');await cloud.locator(':scope > summary').click();
      const writing=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/research/archives/'));
      await cloud.getByRole('button',{name:'保存当前结果到云端',exact:true}).click();const write=await writing;
      check(write.status()===201,await write.text());const item=await write.json();
      const saved=await(await page.request.get(base+'/api/v1/research/archives/'+item.id)).json();
      const p=saved.payload,chart=p.charts[0],fixture=await(await page.request.get(base+'/qa/fixture/'+code+'/DAY')).json();
      check(p.target.kind===kind&&p.target.code===code,'wrong chart identity');
      check(p.target.market===(kind==='stock'?'SZ':kind==='index'?'SH':'1'),'wrong chart market');
      check(chart.category==='DAY'&&chart.metadata.actual_adjust===(kind==='stock'?'QFQ':'NONE'),'wrong chart category/adjust');
      check(canonical(chart.result)===canonical(result),'stored chart analysis changed');
      const expected=fixture.data.filter(row=>row.is_closed);check(chart.bars.length===expected.length,'missing closed bars');
      for(let i=0;i<expected.length;i++)for(const key of ['open','high','low','close','vol','amount'])check(chart.bars[i][key]===expected[i][key],`changed ${code}:${i}.${key}`);
      check(p.cutoff===chart.bars.at(-1).period_end||p.cutoff===chart.metadata.observed_at,'cutoff is not tied to snapshot '+p.cutoff);
      check(chart.frozenIndicators,'missing frozen chart indicators');
      await page.waitForLoadState('networkidle');
      const readonlyStart=requests.length;await page.goto(base+'/account');
      const directory=page.locator('.cloud-archives').first();await directory.locator(':scope > summary').click();
      await directory.locator('li').filter({hasText:saved.name}).first().getByRole('button',{name:'查看原档',exact:true}).click();
      const dialog=page.getByRole('dialog',{name:'云端研究原档'});await dialog.waitFor();
      await dialog.locator('canvas').first().waitFor();
      for(const width of [1440,390,320]) {
        await page.setViewportSize({width,height:1000});await page.screenshot({path:`output/playwright/research-flow-${kind}-${width}.png`,fullPage:true});
        check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow '+kind+width);
      }
      check(!requests.slice(readonlyStart).some(r=>/^\/api\/v1\/(?:bars|chanlun|indicator)/.test(r.path)),'readonly chart fetched or computed');
      reports.push({source,kind,code,archive:item.id,bars:chart.bars.length,cutoff:p.cutoff,metadata:chart.metadata.actual_adjust,readonlyResearch:0});
      await dialog.getByRole('button',{name:'关闭云存档'}).click();await page.setViewportSize({width:1440,height:1000});
    }
    check(!errors.length,'page errors '+errors.join(';'));
    return {reports,automaticRequests:requests.filter(r=>r.origin==='system'&&r.path.startsWith('/api/v1/chanlun')).length,pageErrors:errors};
  }finally {page.off('request',listen);page.off('pageerror',error)}
}
