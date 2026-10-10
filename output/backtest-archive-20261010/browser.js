async (page) => {
  const requests=[],errors=[],receipts=[],results=[];
  const onRequest=r=>requests.push({method:r.method(),path:new URL(r.url()).pathname,origin:r.headers()['x-query-origin']??null,owner:r.headers()['x-task-owner']??null});
  const onError=e=>errors.push(String(e));
  const onResponse=async r=>{if(r.ok()&&r.url().includes('/scan-evidence/'))receipts.push(await r.json());if(r.ok()&&new URL(r.url()).pathname==='/api/v1/backtest/run')results.push(await r.json())};
  page.on('request',onRequest);page.on('pageerror',onError);page.on('response',onResponse);
  const check=(v,m)=>{if(!v)throw Error(m)};
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v);
  try {
    const existing=new Set((await (await page.request.get('http://127.0.0.1:8769/api/v1/research/archives')).json()).items.map(row=>row.id));
    await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:8769/signals');
    const scanned=page.waitForResponse(async r=>new URL(r.url()).pathname.startsWith('/api/v1/backtest/tasks/')&&r.ok()&&(await r.json()).status==='done');
    await page.getByRole('button',{name:'一键扫描',exact:true}).click();await scanned;
    const completed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/backtest/run'&&r.ok());
    await page.getByRole('button',{name:'复核信号',exact:true}).first().click();await completed;
    await page.getByRole('button',{name:'导出回测原档',exact:true}).waitFor();
    const cloud=page.locator('.report-content .cloud-archives');await cloud.locator(':scope > summary').click();
    const writing=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/research/archives/'));
    await cloud.getByRole('button',{name:'保存当前结果到云端',exact:true}).click();const response=await writing;
    check(response.status()===201,await response.text());const summary=await response.json();
    const saved=await (await page.request.get(`http://127.0.0.1:8769/api/v1/research/archives/${summary.id}`)).json();
    check(saved.kind==='backtest','wrong archive kind');check(saved.payload.result.trades.length>0,'empty fixture trades');
    check(canonical(saved.payload.result)===canonical(results.at(-1)),'result fields changed');
    check(canonical(saved.payload.radarSource.receipt)===canonical(receipts.at(-1)),'original source changed');
    check(saved.payload.request.ohlcv.length===800,'original warmup lost');
    check(/^research-execution-v1:[a-f0-9]{64}$/.test(saved.payload.result.execution_version),'execution version missing');
    check(requests.filter(r=>r.path==='/api/v1/backtest/run').every(r=>r.owner&&r.origin==='system'),'automatic review owner or origin incorrect');
    const downloading=page.waitForEvent('download');await page.getByRole('button',{name:'导出回测原档',exact:true}).click();const download=await downloading;
    const file='/Users/bowen/Documents/Python/Google/TDX-work/output/backtest-archive-20261010/export.json';await download.saveAs(file);
    let text='';for await(const chunk of await download.createReadStream())text+=chunk;
    check(canonical(JSON.parse(text))===canonical(saved.payload),'local export differs from original cloud payload');
    await page.request.post('http://127.0.0.1:8769/qa/evict');const source=saved.payload.radarSource.receipt;
    const missing=await page.request.get(`http://127.0.0.1:8769/api/v1/backtest/tasks/${source.task_id}/scan-evidence/${source.row_index}`);check(missing.status()===404,'task not removed');
    const start=requests.length;await page.goto('http://127.0.0.1:8769/account');
    const directory=page.locator('.cloud-archives').first();await directory.locator(':scope > summary').click();
    await directory.getByRole('button',{name:'查看原档',exact:true}).first().click();
    const dialog=page.getByRole('dialog',{name:'云端研究原档'});await dialog.getByText(/回测原档 · SZ:300450/).waitFor();
    check(await dialog.locator('canvas').count()>=2,'missing stored charts');check(await dialog.getByRole('heading',{name:'原成交记录',exact:true}).count()===1,'missing trades');
    const sizes=[];
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});
      await page.waitForFunction(()=>{const d=document.querySelector('dialog[open]'),a=d?.querySelector('.backtest-archive');return d&&a&&d.scrollWidth<=d.clientWidth+1&&a.scrollWidth<=a.clientWidth+1});
      const geometry=await page.evaluate(()=>{const d=document.querySelector('dialog[open]'),a=d.querySelector('.backtest-archive');return {width:innerWidth,scroll:document.documentElement.scrollWidth,dialog:d.getBoundingClientRect().width,dialogOverflow:d.scrollWidth-d.clientWidth,archiveOverflow:a.scrollWidth-a.clientWidth}});
      check(geometry.scroll<=width+1&&geometry.dialog<=width&&geometry.dialogOverflow<=1&&geometry.archiveOverflow<=1,'page or dialog overflow');sizes.push(geometry);
      await page.screenshot({path:`/Users/bowen/Documents/Python/Google/TDX-work/output/playwright/backtest-archive-${width}.png`});
    }
    await dialog.getByRole('button',{name:'关闭云存档',exact:true}).click();
    await directory.getByLabel('选择研究备份文件',{exact:true}).setInputFiles(file);
    await directory.getByRole('button',{name:'确认导入到当前账户',exact:true}).click();
    await directory.getByRole('button',{name:'查看原档',exact:true}).nth(existing.size+1).waitFor();
    const entries=await (await page.request.get('http://127.0.0.1:8769/api/v1/research/archives')).json();check(entries.items.length===existing.size+2,'import did not create independent archive');
    for(const row of entries.items.filter(row=>!existing.has(row.id))){const raw=await (await page.request.get(`http://127.0.0.1:8769/api/v1/research/archives/${row.id}`)).json();check(canonical(raw.payload)===canonical(saved.payload),'import changed original fields')}
    const forbidden=requests.slice(start).filter(r=>/scan-evidence|\/bars(?:\/|$)|\/backtest\/run|\/indicator\/compute|\/chanlun\/(?:replay|observations|archive-recompute)/.test(r.path));
    check(!forbidden.length,JSON.stringify(forbidden));check(!errors.length,JSON.stringify(errors));
    return {bars:saved.payload.request.ohlcv.length,trades:saved.payload.result.trades.length,equity:saved.payload.result.equity_curve.length,originalTask404:missing.status(),exactResult:true,exactSource:true,exportMatchesCloud:true,importMatchesCloud:true,readonlyRequests:forbidden,errors,sizes};
  }finally{page.off('request',onRequest);page.off('pageerror',onError);page.off('response',onResponse)}
}
