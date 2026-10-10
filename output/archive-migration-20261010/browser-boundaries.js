async page => {
  const endpoint='http://127.0.0.1:8768/api/v1/research/archives';
  const directory=async()=> (await (await page.request.get(endpoint)).json());
  const owner=(await (await page.request.get('http://127.0.0.1:8768/api/v1/auth/me')).json()).user.id;
  const initial=await directory(),first=initial.items.find(row=>row.name==='旧档甲');
  const del=await page.request.post(endpoint+'/'+first.id+'/actions',{headers:{'X-Research-Owner':owner,Origin:'http://127.0.0.1:8768'},data:{action:'delete',revision:first.revision}});
  if(!del.ok())throw Error('test trash setup '+del.status());
  await page.reload();await page.getByText('账户云存档',{exact:true}).click();
  await page.getByRole('button',{name:'检查本地快照',exact:true}).click();
  await page.getByText('已检查 4 份，请选择要迁移的原档。',{exact:true}).waitFor();
  await page.getByRole('checkbox',{name:'选择 旧档甲',exact:true}).check();
  await page.getByRole('button',{name:'确认迁移 1 份到当前账户',exact:true}).click();
  await page.getByText('云端已有副本在回收站中，未自动恢复。',{exact:true}).waitFor();
  const trash=(await directory()).items.find(row=>row.id===first.id).state;
  if(trash!=='deleted')throw Error('unexpected restore');
  await page.getByRole('checkbox',{name:'选择 旧档乙',exact:true}).check();
  await page.evaluate(()=>new Promise((resolve,reject)=>{const req=indexedDB.open('tdx-research-snapshots',1);req.onerror=()=>reject(req.error);req.onsuccess=()=>{const db=req.result,tx=db.transaction('snapshots','readwrite'),store=tx.objectStore('snapshots'),get=store.get('qa-migrate-2');get.onsuccess=()=>store.put({...get.result,note:'检查后另一个页面修改了原件'});tx.oncomplete=()=>{db.close();resolve()}}}));
  let writes=0;const watch=req=>{if(req.method()==='PUT'&&req.url().includes('/research/archives/'))writes++};page.on('request',watch);
  await page.getByRole('button',{name:'确认迁移 1 份到当前账户',exact:true}).click();
  await page.getByText('本地原档在检查后发生变化，未上传；请重新检查并确认',{exact:true}).waitFor();
  page.off('request',watch);if(writes)throw Error('changed content uploaded without reconfirmation');
  const layouts=[];
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000});
    await page.getByRole('region',{name:'本地快照迁移'}).scrollIntoViewIfNeeded();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const measured=await page.evaluate(()=>({width:innerWidth,document:document.documentElement.scrollWidth}));
    if(measured.document>width)throw Error('overflow '+JSON.stringify(measured));layouts.push(measured);
    await page.getByRole('region',{name:'本地快照迁移'}).screenshot({path:'output/playwright/archive-migration-'+width+'.png'});
  }
  return {trash,changedSourceWrites:writes,cloudCount:(await directory()).items.length,layouts};
}
