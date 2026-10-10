async (page) => {
  const requests=[],errors=[],receipts=[];
  const onRequest=r=>requests.push({method:r.method(),path:new URL(r.url()).pathname,origin:r.headers()['x-query-origin']??null});
  const onError=e=>errors.push(String(e));
  const onResponse=async r=>{if(r.url().includes('/scan-evidence/')&&r.ok())receipts.push(await r.json())};
  page.on('request',onRequest);page.on('pageerror',onError);page.on('response',onResponse);
  const check=(v,m)=>{if(!v)throw Error(m)};
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v);
  try {
    await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:8769/signals');
    const scanned=page.waitForResponse(async r=>new URL(r.url()).pathname.startsWith('/api/v1/backtest/tasks/')&&r.ok()&&(await r.json()).status==='done');
    await page.getByRole('button',{name:'一键扫描',exact:true}).click();await scanned;
    await page.getByRole('button',{name:'复核信号',exact:true}).first().click();await page.waitForURL(u=>u.searchParams.get('review')==='signal');
    const url=new URL(page.url());url.pathname='/chanlun';
    const analyzed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/chanlun/replay'&&r.ok(),{timeout:60000});await page.goto(url.toString());await analyzed;
    const replayed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/chanlun/replay'&&r.ok(),{timeout:60000});await page.getByRole('button',{name:'回放上一根 K 线',exact:true}).click();await replayed;
    const autoStart=requests.length;
    await page.getByRole('navigation',{name:'缠论工作区'}).getByRole('button',{name:'研究 多周期观察与快照'}).click();
    const study=page.locator('.multi-study');await study.getByText(/本次选定 5 个周期，1 个取得研究结果/).waitFor({timeout:60000});
    const automatic=requests.slice(autoStart).filter(r=>/\/bars(?:\/|$)|\/chanlun\/observations/.test(r.path));
    check(automatic.length===5&&automatic.every(r=>r.origin==='system'),'automatic study query origin was counted as user');
    await study.getByLabel('自动更新',{exact:true}).uncheck();
    const cloud=study.locator('.cloud-archives');await cloud.locator(':scope > summary').click();
    const save=async()=>{
      const pending=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/research/archives/'));
      await cloud.getByRole('button',{name:'保存当前结果到云端',exact:true}).click();const response=await pending;
      check(response.status()===201,await response.text());const record=await response.json();
      return await (await page.request.get(`http://127.0.0.1:8769/api/v1/research/archives/${record.id}`)).json();
    };
    const partial=await save();
    check(partial.payload.result.rows.length===5,'failed periods dropped');
    check(partial.payload.series.length===1,'unexpected invented period inputs');
    check(partial.payload.result.rows.filter(r=>r.error).length===4,'missing collection failures');
    check(partial.payload.result.rows.find(r=>r.category==='DAY').bar_count===799,'study used bars beyond replay cutoff');
    check(canonical(partial.payload.radarSource.receipt)===canonical(receipts.at(-1)),'source receipt changed');
    const downloading=page.waitForEvent('download');await study.getByRole('button',{name:'保存研究快照',exact:true}).click();
    const download=await downloading;await download.saveAs('/Users/bowen/Documents/Python/Google/TDX-work/output/study-lineage-20261010/study-export.json');
    let exported='';for await(const chunk of await download.createReadStream())exported+=chunk;
    check(canonical(JSON.parse(exported))===canonical(partial.payload),'export differs from cloud payload');
    await study.locator('.overview-settings > summary').click();
    for(const input of await study.locator('.study-periods input').all()){if(await input.inputValue()!=='WEEK')await input.uncheck();else await input.check()}
    const manualStart=requests.length;await study.getByRole('button',{name:'更新概览',exact:true}).click();
    await study.getByText(/本次选定 1 个周期，0 个取得研究结果/).waitFor();
    const manual=requests.slice(manualStart).filter(r=>/\/bars(?:\/|$)|\/chanlun\/observations/.test(r.path));
    check(manual.length===1&&manual[0].origin==='user','explicit failed query was not user-origin');
    const failed=await save();check(failed.payload.collection.execution==='not_started'&&failed.payload.series.length===0,'total failure masquerades as computation');
    check(failed.payload.result.rows.length===1&&failed.payload.result.rows[0].error,'failure message missing');
    check(canonical(failed.payload.radarSource)===canonical(partial.payload.radarSource),'failure report lost source');
    await page.request.post('http://127.0.0.1:8769/qa/evict');const source=failed.payload.radarSource;
    const unavailable=await page.request.get(`http://127.0.0.1:8769/api/v1/backtest/tasks/${source.receipt.task_id}/scan-evidence/${source.receipt.row_index}`);check(unavailable.status()===404,'task not cleared');
    const start=requests.length;await page.goto('http://127.0.0.1:8769/account');
    const directory=page.locator('.cloud-archives').first();await directory.locator(':scope > summary').click();
    await directory.getByRole('button',{name:'查看原档',exact:true}).first().click();
    let dialog=page.getByRole('dialog',{name:'云端研究原档'});await dialog.locator('.archived-radar > summary').click();
    check((await dialog.innerText()).includes('800 根已封存'),'empty failure source not shown');
    check((await dialog.innerText()).includes(failed.payload.result.rows[0].error),'original failure not displayed');
    await dialog.getByRole('button',{name:'关闭云存档',exact:true}).click();
    await directory.getByRole('button',{name:'查看原档',exact:true}).nth(1).click();
    dialog=page.getByRole('dialog',{name:'云端研究原档'});await dialog.locator('.archived-radar > summary').click();
    for(const row of partial.payload.result.rows.filter(r=>r.error))check((await dialog.innerText()).includes(row.error),`lost ${row.category} failure`);
    const sizes=[];
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});const geometry=await page.evaluate(()=>({page:document.documentElement.scrollWidth,viewport:innerWidth,dialog:document.querySelector('dialog[open]').getBoundingClientRect().width}));
      check(geometry.page<=width+1&&geometry.dialog<=width,'page overflow');sizes.push({width,...geometry});
      await page.screenshot({path:`/Users/bowen/Documents/Python/Google/TDX-work/output/playwright/study-lineage-${width}.png`});
    }
    const forbidden=requests.slice(start).filter(r=>/scan-evidence|\/bars(?:\/|$)|\/chanlun\/(?:replay|observations|archive-recompute)|\/indicator\/compute/.test(r.path));
    check(forbidden.length===0,JSON.stringify(forbidden));check(errors.length===0,JSON.stringify(errors));
    return {originalBars:source.receipt.bars.length,partial:{rows:partial.payload.result.rows.length,inputs:partial.payload.series.length,failures:4,dayBars:799},totalFailure:failed.payload.collection,automatic,manual,exportMatchesCloud:true,sourceTaskStatus:unavailable.status(),readonlyRequests:forbidden,errors,sizes};
  } finally {page.off('request',onRequest);page.off('pageerror',onError);page.off('response',onResponse)}
}
