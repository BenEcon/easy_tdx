async page => {
  const errors=[],queries=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/\/api\/v1\/(chanlun|bars|indicator)/.test(r.url()))queries.push({url:r.url(),method:r.method(),origin:r.headers()['x-query-origin']})});
  const base='http://127.0.0.1:8768/api/v1/research/archives';
  const list=async()=> (await (await page.request.get(base)).json()).items;
  const initial=await list(),source=initial.find(row=>row.name==='重算测试图表');
  await page.getByRole('listitem').filter({has:page.getByText('重算测试图表',{exact:true})}).getByRole('button',{name:'查看原档',exact:true}).click();
  await page.getByRole('dialog',{name:'云端研究原档'}).waitFor();
  await page.locator('.archive-recompute > summary').click();
  await page.getByRole('button',{name:'检查重算条件',exact:true}).click();
  await page.getByRole('button',{name:'确认按当前版本重算',exact:true}).waitFor();
  if(queries.length)throw Error('original preview/inspection calculated '+JSON.stringify(queries));
  const response=page.waitForResponse(r=>r.url().includes('/chanlun/archive-recompute'));
  await page.getByRole('button',{name:'确认按当前版本重算',exact:true}).click();
  const computed=await response;if(computed.status()!==200)throw Error('compute '+computed.status());
  await page.getByText('所选原档的可重算内容已计算完成；原档未覆盖。请核对差异后决定是否保存新副本。',{exact:true}).waitFor();
  const diffs=await page.getByRole('region',{name:'原档与重算差异表'}).count();
  const cells=await page.locator('.diff-scroll').innerText();
  if(!cells.includes('$["macd"]["dif"][20]'))throw Error('missing unrounded diff');
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出完整对照记录',exact:true}).click();
  await (await download).saveAs('/Users/bowen/Documents/Python/Google/TDX-work/output/archive-recompute-20261010/chart-comparison.json');
  await page.getByRole('button',{name:'另存重算新副本',exact:true}).click();
  await page.getByRole('button',{name:'新副本已保存',exact:true}).waitFor();
  const after=await list(),old=after.find(row=>row.id===source.id),fresh=after.find(row=>row.name==='重算测试图表 · 重算');
  if(after.length!==3||old.digest!==source.digest||old.revision!==source.revision||!fresh)throw Error('archive overwritten or new copy missing');
  const content=await (await page.request.get(base+'/'+fresh.id)).json();
  if(content.payload.recomputation.source_archive.id!==source.id||content.payload.charts[0].frozenIndicators!==undefined)throw Error('lineage/frozen mismatch');
  const layouts=[];
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000});await page.locator('.archive-recompute').scrollIntoViewIfNeeded();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const layout=await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth}));if(layout.document>width)throw Error('page overflow');layouts.push(layout);
    await page.locator('.archive-recompute').screenshot({path:'output/playwright/archive-recompute-'+width+'.png'});
  }
  if(errors.length)throw Error(JSON.stringify(errors));
  return {queries,sourceUnchanged:true,newId:fresh.id,changes:cells,layouts,errors,diffs};
}
