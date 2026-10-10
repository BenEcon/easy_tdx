import { shallowRef } from 'vue'
import { queryAction } from './query-origin.ts'
import { isTaskFailure, isTaskTerminal, taskFailureMessage, taskLabels } from './task-state.ts'
import type { TaskState, TaskSubmitResponse } from './types'
import {validateTaskProgress} from './task-progress.ts'

export interface TaskRequestContext { owner: string; signal: AbortSignal }

/** Detach JSON-shaped request data from reactive, editable forms without changing numbers. */
export function copyTaskInput<T>(value: T): T {
  if (Array.isArray(value)) return value.map(copyTaskInput) as T
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,copyTaskInput(v)])) as T
  }
  return value
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    const finish=()=>{clearTimeout(timer);signal.removeEventListener('abort',finish);resolve()}
    const timer=setTimeout(finish,ms)
    signal.addEventListener('abort',finish,{once:true})
    if(signal.aborted)finish()
  })
}

/** UI attachment only: invalidation stops local polling, NEVER claims to cancel a server task. */
export function taskExecution<Request, Result>(options: {
  owner:()=>string|undefined
  submit:(request:Request,context:TaskRequestContext)=>Promise<TaskSubmitResponse>
  poll:(id:string,context:TaskRequestContext)=>Promise<TaskState>
  cancel?:(id:string,context:TaskRequestContext)=>Promise<TaskState>
  timeout:number
  interval:number
}) {
  const result=shallowRef<Result|null>(null), request=shallowRef<Request|null>(null)
  const running=shallowRef(false), error=shallowRef(''), taskId=shallowRef('')
  const state=shallowRef<TaskState|null>(null),cancelError=shallowRef(''),cancelling=shallowRef(false)
  let generation=0,controller:AbortController|null=null
  function clear() {
    generation++;controller?.abort();controller=null
    running.value=false;result.value=null;request.value=null;error.value='';taskId.value=''
    state.value=null;cancelError.value='';cancelling.value=false
  }
  async function cancel():Promise<void> {
    const id=taskId.value,owner=options.owner(),version=generation,active=controller
    if(!options.cancel||!running.value||!id||!owner||!active||cancelling.value)return
    const current=()=>version===generation&&options.owner()===owner
    cancelling.value=true;cancelError.value=''
    try {
      const response=await options.cancel(id,{owner,signal:active.signal})
      if(!current()||!running.value)return
      if(response.task_id!==id||!Object.hasOwn(taskLabels,response.status))throw Error('取消响应不匹配，请查询任务状态')
      state.value=response // only polling publishes a complete result, never this acknowledgement
    }catch(e){if(current())cancelError.value=e instanceof Error?e.message:String(e)}
    finally{if(current())cancelling.value=false}
  }
  async function run(input:Request,manual=true):Promise<boolean> {
    clear()
    const version=generation,owner=options.owner()
    if(!owner){error.value='请先登录后再提交计算';return false}
    const active=new AbortController();controller=active
    const context={owner,signal:active.signal}
    const current=()=>version===generation&&options.owner()===owner
    let expired=false
    const deadline=setTimeout(()=>{expired=true;active.abort()},options.timeout)
    const timeoutMessage='等待已超时，任务可能仍在计算，请到个人账户查看或取消'
    running.value=true
    try {
      const captured=copyTaskInput(input)
      const submitted=await queryAction(manual)(()=>options.submit(copyTaskInput(captured),context))
      if(!current())return false
      if(expired)throw Error(timeoutMessage)
      if(typeof submitted.task_id!=='string'||!submitted.task_id)throw Error('任务提交未返回有效编号')
      const id=submitted.task_id;taskId.value=id
      while(current()) {
        const observed=await options.poll(id,context)
        if(!current())return false
        if(expired)throw Error(timeoutMessage)
        if(observed.task_id!==id)throw Error('任务响应编号不一致，未采用该结果')
        if(!Object.hasOwn(taskLabels,observed.status))throw Error('任务状态不可识别，未采用该结果')
        validateTaskProgress(observed.progress)
        const acknowledged=state.value?.status
        const staleActive=acknowledged&&(isTaskTerminal(acknowledged)||acknowledged==='cancelling')&&['pending','running'].includes(observed.status)
        if(!staleActive)state.value=observed
        if(observed.status==='done') {
          if(!observed.result||typeof observed.result!=='object'||Array.isArray(observed.result))throw Error('任务已结束但没有有效结果')
          result.value=observed.result as Result;request.value=captured
          return true
        }
        if(isTaskFailure(observed.status))throw Error(taskFailureMessage(observed))
        await wait(options.interval,active.signal)
        if(expired)throw Error(timeoutMessage)
      }
      return false
    } catch(e) {
      if(current())error.value=expired?timeoutMessage:e instanceof Error?e.message:String(e)
      return false
    } finally {
      clearTimeout(deadline)
      if(current()){running.value=false;controller=null}
    }
  }
  return{result,request,running,error,taskId,state,cancelError,cancelling,run,clear,cancel}
}
