async page => {
  const group={id:'qa',name:'布局验收（模拟数据）',targets:[{kind:'stock',market:'SZ',code:'000001',name:'模拟标的'}]};
  const user={id:'scroll-qa',username:'布局验收',role:'admin',active:true,tracking_allowed:true,preferences:{tracking_groups:{version:1,revision:'qa',groups:[group]}}};
  await page.unroute('**/api/**');
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    let body={data:[],items:[],count:0,ok:true};
    if(path.endsWith('/auth/status'))body={user,authenticated:true,setup_required:false};
    else if(path.endsWith('/auth/activity'))body={active:true,role:'admin',tracking_allowed:true};
    else if(path.endsWith('/auth/me')||path.endsWith('/auth/me/preferences'))body={user};
    else if(path.endsWith('/research/factors'))body=Array.from({length:18},(_,i)=>({name:'qa_'+i,description:'布局验收因子 '+i,category:'qa'+Math.floor(i/3)}));
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
  await page.goto('http://127.0.0.1:8771/quant-research');
  await page.waitForSelector('.quant-page');
  console.log(await page.locator('.quant-page').evaluate(el=>({height:el.clientHeight,scroll:el.scrollHeight,overflow:getComputedStyle(el).overflowY})));
}
