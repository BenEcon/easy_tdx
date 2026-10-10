async page => {
  await page.reload();await page.getByText('账户云存档',{exact:true}).click();
  await page.getByRole('listitem').filter({has:page.getByText('重算测试研究',{exact:true})}).getByRole('button',{name:'查看原档',exact:true}).click();
  await page.locator('.archive-recompute > summary').click();
  await page.getByRole('button',{name:'检查重算条件',exact:true}).click();
  let release;const gate=new Promise(resolve=>release=resolve);let interceptedResolve;const intercepted=new Promise(resolve=>interceptedResolve=resolve);
  const held=async route=>{const response=await route.fetch();interceptedResolve();await gate;try{await route.fulfill({response})}catch{}};
  await page.route('**/api/v1/chanlun/archive-recompute',held);
  await page.getByRole('button',{name:'确认按当前版本重算',exact:true}).click();await intercepted;
  await page.getByRole('button',{name:'取消等待',exact:true}).click();release();
  await page.getByText('已取消等待；服务端已开始的计算或保存可能继续。原档未修改，未将未完成重算标为完成。',{exact:true}).waitFor();
  if(await page.getByRole('button',{name:'另存重算新副本',exact:true}).count())throw Error('cancelled result enabled saving');
  await page.unroute('**/api/v1/chanlun/archive-recompute',held);
  const response=page.waitForResponse(r=>r.url().includes('/chanlun/archive-recompute'));
  await page.getByRole('button',{name:'确认按当前版本重算',exact:true}).click();const r=await response;
  const sent=r.request().postDataJSON(),body=await r.json();
  await page.getByText('所选原档的可重算内容已计算完成；原档未覆盖。请核对差异后决定是否保存新副本。',{exact:true}).waitFor();
  if(sent.study.volume_multiple!==3||sent.study.window_bars!==30||JSON.stringify(sent.study.ma_periods)!=='[5,13]'||sent.study.series[0].bar_time!=='start')throw Error('parameters replaced');
  const before=await (await page.request.get('http://127.0.0.1:8768/api/v1/research/archives')).json(),original=before.items.find(row=>row.name==='重算测试研究');
  await page.getByRole('button',{name:'另存重算新副本',exact:true}).click();await page.getByRole('button',{name:'新副本已保存',exact:true}).waitFor();
  const after=await (await page.request.get('http://127.0.0.1:8768/api/v1/research/archives')).json(),same=after.items.find(row=>row.id===original.id);
  if(after.items.length!==before.items.length+1||same.digest!==original.digest)throw Error('study archive replaced');
  const activity=await (await page.request.get('http://127.0.0.1:8768/api/v1/admin/activity/events?kind=query')).json();
  return {cancelPreventedSave:true,parameters:body.parameters,sourceUnchanged:true,cloudCount:after.items.length,activity:activity.items.map(row=>({feature:row.feature,details:row.details,origin:row.query_origin}))};
}
