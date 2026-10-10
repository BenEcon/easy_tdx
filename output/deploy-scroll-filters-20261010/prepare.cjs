const fs=require('fs'),root=process.cwd(),stable=root+'/output/deploy-scroll-filters-20261010/stable/web-ui/src/',live=root+'/web-ui/src/';
console.log('*** Begin Patch');
function patch(p,next){
 if(!fs.existsSync(p)){console.log('*** Add File: '+p+'\n'+next.split('\n').map(x=>'+'+x).join('\n'));return}
 const old=fs.readFileSync(p,'utf8');if(old===next)return;
 console.log('*** Update File: '+p);
 const a=old.trimEnd().split('\n'),b=next.trimEnd().split('\n');let i=0,j=0;
 while(i<a.length||j<b.length){if(a[i]===b[j]){i++;j++;continue}let ni=a.length,nj=b.length,best=Infinity;
 for(let x=i;x<a.length;x++)for(let y=j;y<b.length&&x-i+y-j<best;y++)if(a[x]===b[y]){ni=x;nj=y;best=x-i+y-j;break}
 console.log('@@');if(i>0)console.log(' '+a[i-1]);for(;i<ni;i++)console.log('-'+a[i]);for(;j<nj;j++)console.log('+'+b[j]);
 }
}
for(const f of ['tracking-filters.ts','components/TrackingBreadth.vue'])patch(stable+f,fs.readFileSync(live+f,'utf8'));
const f='views/TrackingView.vue',main=fs.readFileSync(live+f,'utf8');let s=fs.readFileSync(stable+f,'utf8');
s=s.replace('readTrackingBook, matchesBreadth,','readTrackingBook,').replace("import TrackingBreadth from '../components/TrackingBreadth.vue'", "import TrackingBreadth from '../components/TrackingBreadth.vue'\nimport {matchesBreadthFilters,matchesTrackingStatus} from '../tracking-filters'");
s=s.replace(/const query = ref\(''\)[\s\S]*?(?=const page = ref)/,main.match(/const query = ref\(''\)[\s\S]*?(?=const page = ref)/)[0]);
s=s.replace("watch([query,filter],()=>{page.value=1})", "watch([query,filter],()=>{page.value=1;inspected.value=''}, {deep:true})").replaceAll('breadthFilter.value=null','breadthFilter.value=[]').replace('return breadthFilter.value ? row.study?.rows.find(item => item.category===breadthFilter.value!.category)', 'return breadthFilter.value.length ? row.study?.rows.find(item => item.category===breadthFilter.value[0]!.category)');
s=s.replace('<label>状态<MacSelect v-model="filter" :options="filterOptions" aria-label="分析结果状态" /></label>',main.match(/<fieldset class="status-filters">.*?<\/fieldset>/)[0]).replace('aria-label="追踪分析表，可横向滚动"','aria-label="追踪分析表，独立上下及左右滚动"').replace('overscroll-behavior-y:auto','overscroll-behavior-y:contain').replace('</style>',main.slice(main.indexOf('\n.tracking-view{box-sizing:border-box;')));
patch(stable+f,s);
const a='components/TrackingArchivePreview.vue';s=fs.readFileSync(stable+a,'utf8').replace('trackingTitle,matchesBreadth,','trackingTitle,').replace("import TrackingBreadth from './TrackingBreadth.vue'", "import TrackingBreadth from './TrackingBreadth.vue'\nimport {matchesBreadthFilters} from '../tracking-filters'").replace('ref<BreadthFilter|null>(null)','ref<BreadthFilter[]>([])').replace('!breadthFilter.value||matchesBreadth(r,breadthFilter.value)','matchesBreadthFilters(r,breadthFilter.value)');patch(stable+a,s);
const css=`
/* The route owns vertical scrolling; grids retain their own data scrolling. */
.quant-page{box-sizing:border-box;overflow-y:auto;overflow-x:hidden;overscroll-behavior-y:contain;scrollbar-gutter:stable;padding-bottom:max(24px,env(safe-area-inset-bottom))}
.quant-page>header,.quant-page>section,.quant-page>.status-banner{flex-shrink:0}
.factor-output{flex:none;min-height:460px}
.factor-output>.result-table{height:clamp(420px,60dvh,680px);flex:1;min-width:0}
.factor-library{flex-shrink:0;min-height:180px}
.metric-rail{min-width:0;flex-shrink:0;max-height:680px}
.risk-workspace{flex:none;min-height:650px;align-items:start}
.risk-results{min-width:0;grid-template-rows:auto minmax(260px,auto) minmax(260px,auto)}
.risk-config{min-width:0;overflow:visible}
.risk-table,.correlation-table{height:300px;min-width:0}
@media(max-width:760px){.factor-output{flex-direction:column}.factor-output>.metric-rail{width:100%;max-height:180px}.factor-output>.result-table{flex:none;width:100%;height:460px;box-sizing:border-box}.factor-controls{flex-wrap:wrap}.selected-count{margin-left:0}.risk-workspace{grid-template-columns:minmax(0,1fr)}.risk-config{min-height:0}.risk-results{min-width:0}.quant-header{flex-wrap:wrap;gap:12px}}
`;
for(const base of [stable,live]){const p=base+'views/QuantResearchView.vue';patch(p,fs.readFileSync(p,'utf8').replace('</style>',css+'</style>'));}
console.log('*** End Patch');
