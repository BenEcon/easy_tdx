import {onMounted,onBeforeUnmount,watch} from 'vue'
import {useAuth,applyActivityAccess,clearExpiredActivityUser} from './auth'
import {activityEligible,ACTIVE_IDLE_MS} from './activity'

export function useActivity() {
  const {currentUser}=useAuth()
  let lastAction=-Infinity, restart=true, busy=false, timer:ReturnType<typeof setInterval>|undefined
  function action(){
    const now=performance.now()
    if(now-lastAction>=ACTIVE_IDLE_MS) restart=true
    lastAction=now
  }
  function visibility(){restart=true;if(document.visibilityState==='visible'&&document.hasFocus()) action();else lastAction=-Infinity}
  async function ping(){
    const owner=currentUser.value?.id
    if(!owner||busy||!activityEligible(document.visibilityState==='visible',document.hasFocus(),lastAction,performance.now())) return
    const baseline=restart; restart=false;busy=true
    try{
      const response=await fetch('/api/v1/auth/activity',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Research-Owner':owner},body:JSON.stringify({restart:baseline}),signal:AbortSignal.timeout(8000)})
      if(response.ok)applyActivityAccess(owner,await response.json())
      else if(response.status===401)clearExpiredActivityUser(owner)
      else restart=true
    }catch{restart=true}finally{busy=false}
  }
  watch(()=>currentUser.value?.id,()=>{restart=true;action()})
  const events=['pointerdown','pointermove','keydown','wheel','touchstart'] as const
  onMounted(()=>{action();for(const event of events)window.addEventListener(event,action,{passive:true});document.addEventListener('visibilitychange',visibility);window.addEventListener('focus',visibility);window.addEventListener('blur',visibility);timer=setInterval(()=>void ping(),15000);void ping()})
  onBeforeUnmount(()=>{clearInterval(timer);for(const event of events)window.removeEventListener(event,action);document.removeEventListener('visibilitychange',visibility);window.removeEventListener('focus',visibility);window.removeEventListener('blur',visibility)})
}
