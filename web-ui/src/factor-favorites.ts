import {computed,ref,watch,type Ref} from 'vue'

export const FACTOR_FAVORITES_KEY='factor_favorites_v1'
export function parseFactorFavorites(value:unknown):string[]{
  if(value===undefined)return []
  if(!Array.isArray(value)||value.length>512||value.some(v=>typeof v!=='string'||!/^[A-Za-z][A-Za-z0-9_]{0,95}$/.test(v)))throw Error('因子收藏格式异常，原设置未覆盖')
  return [...new Set(value)]
}
type Owner={id:string;preferences:Record<string,unknown>}
/** One shared writer per browser session. Save acknowledgment, not optimistic success. */
export function factorFavoriteState(user:Readonly<Ref<Owner|null>>,save:(patch:Record<string,unknown>)=>Promise<void>){
  const saving=ref(false),error=ref('');let epoch=0,observedOwner:string|undefined
  const read=()=>{try{return{items:parseFactorFavorites(user.value?.preferences[FACTOR_FAVORITES_KEY]),error:''}}catch(e){return{items:[] as string[],error:String(e)}}}
  const parsed=ref(read())
  watch([()=>user.value?.id,()=>user.value?.preferences[FACTOR_FAVORITES_KEY]],()=>{
    if(observedOwner!==user.value?.id){observedOwner=user.value?.id;epoch++;saving.value=false;error.value=''}
    // The generic preference queue may expose pending patches while another
    // preference is acknowledged. Do not claim this collection is saved yet.
    if(!saving.value)parsed.value=read()
  },{immediate:true,flush:'sync',deep:true})
  const items=computed(()=>parsed.value.items),message=computed(()=>error.value||parsed.value.error)
  async function toggle(name:string){
    if(saving.value)return
    error.value=''
    if(!user.value){error.value='请先登录，收藏按账户保存';return}
    if(parsed.value.error){error.value=parsed.value.error;return}
    const stamp=epoch,owner=user.value.id
    try{
      parseFactorFavorites([name])
      const next=items.value.includes(name)?items.value.filter(v=>v!==name):[...items.value,name]
      parseFactorFavorites(next);saving.value=true
      await save({[FACTOR_FAVORITES_KEY]:next})
      if(stamp===epoch&&user.value?.id===owner)parsed.value=read()
    }catch(e){if(stamp===epoch&&user.value?.id===owner)error.value=`收藏未保存：${e instanceof Error?e.message:String(e)}。请重试。`}
    finally{if(stamp===epoch&&user.value?.id===owner)saving.value=false}
  }
  return {items,saving,message,toggle}
}
