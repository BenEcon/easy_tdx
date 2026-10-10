async page => {
 const results=[];
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:820});
  const container=width<760?'.app-main':'.quant-page';
  await page.locator(container).evaluate(el=>el.scrollTop=el.scrollHeight);
  const q=await page.locator(container).evaluate(el=>({height:el.clientHeight,scroll:el.scrollHeight,top:el.scrollTop,bottom:el.getBoundingClientRect().bottom,tableBottom:el.querySelector('.factor-output').getBoundingClientRect().bottom,width:document.documentElement.scrollWidth}));
  if(q.top<=0||q.tableBottom>q.bottom+1||q.width>width)throw Error('factor scroll '+JSON.stringify(q));
  results.push({width,factor:q});
  await page.screenshot({path:'output/playwright/scroll-factors-'+width+'.png'});
 }
 await page.setViewportSize({width:1440,height:820});
 await page.getByRole('button',{name:'组合风险',exact:true}).click();
 await page.locator('.quant-page').evaluate(el=>el.scrollTop=el.scrollHeight);
 const risk=await page.locator('.quant-page').evaluate(el=>({top:el.scrollTop,bottom:el.getBoundingClientRect().bottom,last:el.querySelector('.correlation-table').getBoundingClientRect().bottom}));
 if(risk.last>risk.bottom+1)throw Error('risk clipped');results.push({risk});
 await page.getByRole('link',{name:'追踪标的',exact:true}).click();
 await page.waitForSelector('.tracking-view');
 await page.evaluate(async()=>{
  const {trackingSession:s}=await import('/src/tracking-background.ts');
  const pair={fast:1,slow:2,description:'仅用于布局验收'};
  const study=(direction,category)=>({category,price:10,pairs:{ma:pair,volume:pair,macd:pair},ma_research:{bull:{},bear:{}},direction_observation:{strict:{direction},description:'模拟观察'},divergences:[],buy_sell_points:[],observations:[],window:{start:'2026-01-01',end:'2026-10-09',count:100}});
  s.snapshot.value={group:{id:'qa',name:'布局验收（模拟数据）',targets:[{kind:'stock',market:'SZ',code:'000001',name:'模拟标的'}]},revision:'qa',periods:['DAY','WEEK']};
  s.selectedId.value='qa';s.periods.value=['DAY','WEEK'];s.phase.value='模拟结果 · 仅验证布局';
  s.rows.value=Array.from({length:80},(_,i)=>({target:{kind:'stock',market:'SZ',code:String(300000+i),name:'模拟标的'+i},sources:['模拟来源'],state:i%4===0?'error':'done',study:{rule_version:'qa',rows:[study(i%2?'up':'down','DAY'),study('down','WEEK')]}}));
 });
 await page.waitForSelector('.result-scroll');
 await page.locator('.result-scroll').scrollIntoViewIfNeeded();
 const before=await page.locator('.tracking-view').evaluate(e=>e.scrollTop);
 const box=await page.locator('.result-scroll').boundingBox();
 await page.mouse.move(box.x+100,box.y+100);await page.mouse.wheel(0,400);
 await page.waitForTimeout(350);
 const inner=await page.locator('.result-scroll').evaluate(e=>({top:e.scrollTop,height:e.clientHeight,scroll:e.scrollHeight,overscroll:getComputedStyle(e).overscrollBehaviorY}));
 const after=await page.locator('.tracking-view').evaluate(e=>e.scrollTop);
 if(inner.top<=0||after!==before||inner.overscroll!=='contain')throw Error('independent scrolling '+JSON.stringify({before,after,inner}));
 await page.locator('.result-scroll').evaluate(e=>e.scrollTop=e.scrollHeight);
 await page.mouse.wheel(0,900);await page.waitForTimeout(350);
 if(await page.locator('.tracking-view').evaluate(e=>e.scrollTop)!==after)throw Error('scroll chained at bottom');
 results.push({tracking:{before,after,inner}});
 await page.getByRole('button',{name:'日线 · 最近严格笔向上 · 40 个标的',exact:true}).click();
 await page.getByRole('button',{name:'日线 · 最近严格笔向下 · 40 个标的',exact:true}).click();
 if(await page.locator('.tracking-breadth button[aria-pressed=true]').count()!==2)throw Error('multiselect missing');
 await page.getByRole('button',{name:'周线 · 最近严格笔向下 · 80 个标的',exact:true}).click();
 await page.getByLabel('分析成功',{exact:true}).check();await page.getByLabel('分析失败',{exact:true}).check();
 if(!await page.locator('.result-tools').innerText().then(t=>t.includes('80 个匹配标的')))throw Error('status OR mismatch');
 await page.getByLabel('分析失败',{exact:true}).uncheck();
 if(!await page.locator('.result-tools').innerText().then(t=>t.includes('60 个匹配标的')))throw Error('status removal mismatch');
 if(await page.locator('.result-scroll').evaluate(e=>e.scrollTop)!==0)throw Error('filter did not reset table to first row');
 results.push({multiselect:'3 breadth selections + 2 statuses; 80 then 60 rows'});
 await page.screenshot({path:'output/playwright/scroll-tracking-desktop.png'});
 await page.setViewportSize({width:390,height:820});
 await page.locator('.result-tools').scrollIntoViewIfNeeded();
 const mobile=await page.locator('.tracking-view').evaluate(el=>({width:document.documentElement.scrollWidth,height:el.clientHeight,scroll:el.scrollHeight,innerHeight:el.querySelector('.result-scroll').clientHeight,innerScroll:el.querySelector('.result-scroll').scrollHeight}));
 if(mobile.width>390||mobile.innerScroll<=mobile.innerHeight)throw Error('mobile overflow');
 results.push({mobile});await page.screenshot({path:'output/playwright/scroll-tracking-mobile.png'});
 return results;
}
