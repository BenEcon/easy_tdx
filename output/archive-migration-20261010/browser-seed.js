async page => {
  const result = await page.evaluate(async () => {
    const owner=(await (await fetch('/api/v1/auth/me')).json()).user.id;
    const base={schema:1,id:'qa-migrate-1',owner,name:'旧档甲',note:'保留原始精度',title:'300750',cutoff:'2026-10-09 15:00:00',savedAt:'2026-10-09T08:00:00Z',frontendVersion:'qa-legacy',ruleVersions:[2026100414],history:true,
      target:{kind:'stock',code:'300750'},preferences:{},layers:{bis:true,xds:false,zss:false,bcs:true,mmds:true},
      charts:[{category:'DAY',bars:[{datetime:'2026-10-09 00:00:00',open:1.123456789,close:2,high:3,low:1,vol:100,amount:200}],metadata:{actual_adjust:'QFQ',observed_at:'2026-10-09 16:00:00'},result:{code:'300750',frequency:'day',bis:[],xds:[],zss:[],bcs:[],mmds:[],unknown:{rule:'retain'}}}]};
    const values=[base,{...base,id:'qa-migrate-2',name:'旧档乙'},{...base,id:'qa-migrate-3',name:'旧档丙'},{...base,id:'qa-invalid',name:'损坏旧档',charts:null},{...base,id:'qa-foreign',owner:'other-owner',name:'其他账户不可见'}];
    await new Promise((resolve,reject)=>{const req=indexedDB.open('tdx-research-snapshots',1);req.onupgradeneeded=()=>req.result.createObjectStore('snapshots',{keyPath:'id'}).createIndex('owner','owner');req.onerror=()=>reject(req.error);req.onsuccess=()=>{const db=req.result,tx=db.transaction('snapshots','readwrite');values.forEach(value=>tx.objectStore('snapshots').put(value));tx.oncomplete=()=>{db.close();resolve()};tx.onerror=()=>reject(tx.error)}});
    return {owner,seeded:values.length};
  });
  await page.getByText('账户云存档',{exact:true}).click();
  await page.getByRole('button',{name:'检查本地快照',exact:true}).click();
  await page.getByText('已检查 4 份，请选择要迁移的原档。',{exact:true}).waitFor();
  return {...result,text:await page.getByRole('region',{name:'本地快照迁移'}).innerText(),before:(await (await page.request.get('http://127.0.0.1:8768/api/v1/research/archives')).json()).items.length};
}
