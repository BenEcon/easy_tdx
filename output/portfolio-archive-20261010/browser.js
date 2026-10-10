async (page) => {
  const root='http://127.0.0.1:8769',requests=[],errors=[];
  const onRequest=r=>requests.push({path:new URL(r.url()).pathname,method:r.method(),origin:r.headers()['x-query-origin']??null});
  const onError=e=>errors.push(String(e));page.on('request',onRequest);page.on('pageerror',onError);
  const check=(v,m)=>{if(!v)throw Error(m)};
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v);
  try {
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(root+'/portfolio?stocks=SZ:300450,SH:600699&category=DAY&strategy=ma_cross&params=%7B%22fast%22:7,%22slow%22:31%7D');
    const completed=page.waitForResponse(async r=>new URL(r.url()).pathname.startsWith('/api/v1/backtest/tasks/')&&r.ok()&&(await r.json()).status==='done');
    await page.getByRole('button',{name:'开始组合回测',exact:true}).click();const done=await (await completed).json();
    await page.getByRole('button',{name:'读取完整原档',exact:true}).waitFor();
    check(!requests.some(r=>r.path.endsWith('/portfolio-evidence')),'auto receipt fetch');
    const reading=page.waitForResponse(r=>r.url().endsWith('/portfolio-evidence'));
    await page.getByRole('button',{name:'读取完整原档',exact:true}).click();const receiptResponse=await reading;check(receiptResponse.ok(),await receiptResponse.text());const receipt=await receiptResponse.json();
    await page.getByRole('button',{name:'导出完整 JSON',exact:true}).waitFor();
    check(canonical(receipt.result)===canonical(done.result),'receipt result mismatch');
    const cloud=page.locator('.portfolio-archive-tools .cloud-archives');await cloud.locator(':scope > summary').click();
    const writing=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/research/archives/'));
    await cloud.getByRole('button',{name:'保存当前结果到云端',exact:true}).click();const response=await writing;check(response.status()===201,await response.text());
    const savedId=(await response.json()).id,saved=await (await page.request.get(root+'/api/v1/research/archives/'+savedId)).json();
    check(canonical(saved.payload.receipt)===canonical(receipt),'saved receipt changed');
    const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出完整 JSON',exact:true}).click();const download=await downloading;
    await download.saveAs('/Users/bowen/Documents/Python/Google/TDX-work/output/portfolio-archive-20261010/export.json');
    let text='';for await(const chunk of await download.createReadStream())text+=chunk;
    check(canonical(JSON.parse(text))===canonical(saved.payload),'export changed');
    const removed=await page.request.post(root+'/qa/evict');check(removed.ok(),await removed.text());
    check((await page.request.get(root+'/api/v1/backtest/tasks/'+done.task_id+'/portfolio-evidence')).status()===404,'task retained');
    const start=requests.length;await page.goto(root+'/account');
    const directory=page.locator('.cloud-archives').first();await directory.locator(':scope > summary').click();await directory.getByRole('button',{name:'查看原档',exact:true}).first().click();
    const dialog=page.getByRole('dialog',{name:'云端研究原档'});await dialog.getByText(/组合原档 · 2 个成员/).waitFor();
    check(await dialog.locator('canvas').count()>=3,'missing stored charts');
    await dialog.getByRole('combobox',{name:'原档成员',exact:true}).click();await page.getByRole('option',{name:/SH600699/}).click();
    await dialog.getByText(/SH:600699 · DAY · 资金占比/).waitFor();
    const sizes=[];
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});
      await page.waitForFunction(()=>[...document.querySelectorAll('dialog[open] canvas')].every(c=>c.getBoundingClientRect().width<=document.querySelector('dialog[open]').clientWidth));
      await page.screenshot({path:`output/playwright/portfolio-archive-${width}.png`});
      const geometry=await dialog.evaluate(el=>({page:document.documentElement.scrollWidth,client:el.clientWidth,scroll:el.scrollWidth}));sizes.push({width,...geometry});check(geometry.page<=width&&geometry.scroll<=geometry.client+1,'mobile overflow');
    }
    check(!requests.slice(start).some(r=>/\/bars|\/indicator|\/backtest\/.*run|portfolio-evidence|recompute/.test(r.path)),'readonly triggered research');
    check(requests.filter(r=>r.path.endsWith('/portfolio-evidence')).every(r=>r.origin!=='user'),'receipt counted as manual research');
    check(errors.length===0,'page errors: '+errors.join(';'));
    return {id:savedId,kind:receipt.kind,members:receipt.members.map(m=>({key:m.key,bars:m.bars.length,trades:receipt.result.individual_results[m.key].trades.length})),sizes,errors,receiptRequests:requests.filter(r=>r.path.endsWith('/portfolio-evidence'))};
  }finally{page.off('request',onRequest);page.off('pageerror',onError)}
}
