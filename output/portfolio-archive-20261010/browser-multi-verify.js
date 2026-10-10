async (page) => {
  const root='http://127.0.0.1:8769',requests=[],errors=[];
  const onRequest=r=>requests.push(new URL(r.url()).pathname),onError=e=>errors.push(String(e));
  const check=(v,m)=>{if(!v)throw Error(m)};
  const canonical=v=>JSON.stringify(v&&typeof v==='object'?(Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))]))):v);
  const directory=await (await page.request.get(root+'/api/v1/research/archives')).json();
  const rows=directory.items.filter(r=>r.name==='多策略回测原档');check(rows.length===2,'need original plus imported copy');
  const original=await (await page.request.get(root+'/api/v1/research/archives/'+rows[0].id)).json(),copy=await (await page.request.get(root+'/api/v1/research/archives/'+rows[1].id)).json();
  check(canonical(original.payload)===canonical(copy.payload),'copy differs');const receipt=original.payload.receipt;
  check(receipt.kind==='multi_strategy'&&receipt.members.length===2,'wrong receipt');
  check((await page.request.get(root+'/api/v1/backtest/tasks/'+receipt.task_id+'/portfolio-evidence')).status()===404,'source should be gone');
  page.on('request',onRequest);page.on('pageerror',onError);
  try {
    await page.goto(root+'/account');const cloud=page.locator('.cloud-archives').first();await cloud.locator(':scope > summary').click();await cloud.getByRole('button',{name:'查看原档',exact:true}).first().click();
    const dialog=page.getByRole('dialog',{name:'云端研究原档'});await dialog.getByText(/多策略原档 · 2 个成员/).waitFor();
    await dialog.getByRole('combobox',{name:'原档成员',exact:true}).click();await page.getByRole('option',{name:/分钟观察/}).click();await dialog.getByText(/SZ:300750 · MIN_30 · 资金占比/).waitFor();
    const sizes=[];for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});await page.waitForFunction(()=>[...document.querySelectorAll('dialog[open] canvas')].every(c=>c.getBoundingClientRect().width<=document.querySelector('dialog[open]').clientWidth));
      await page.screenshot({path:`output/playwright/multi-archive-${width}.png`});const geometry=await dialog.evaluate(el=>({page:document.documentElement.scrollWidth,client:el.clientWidth,scroll:el.scrollWidth}));sizes.push({width,...geometry});check(geometry.page<=width&&geometry.scroll<=geometry.client+1,'overflow');
    }
    const forbidden=requests.filter(p=>/\/bars|\/indicator|\/backtest\/.*run|portfolio-evidence|recompute/.test(p));check(!forbidden.length,'readonly requests');check(!errors.length,errors.join(';'));
    return {ids:rows.map(r=>r.id),members:receipt.members.map(m=>({key:m.key,bars:m.bars.length,trades:receipt.result.individual_results[m.key].trades.length})),sizes,forbidden,errors};
  }finally{page.off('request',onRequest);page.off('pageerror',onError)}
}
