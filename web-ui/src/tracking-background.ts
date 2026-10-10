import {effectScope,watch} from 'vue'
import {useAuth} from './auth'
import {canUseTracking} from './feature-access.ts'
import {createTrackingSession} from './tracking-session.ts'
import {createTrackingAutoSave} from './tracking-autosave.ts'

const {currentUser}=useAuth()
export const trackingAutoSave=createTrackingAutoSave(()=>currentUser.value?.id)
export const trackingSession=createTrackingSession(payload=>trackingAutoSave.save(payload),()=>!trackingAutoSave.pending.value)
// Module-level watcher survives route unmounts. Loss of access clears private
// results and prevents any in-flight result from crossing an account boundary.
effectScope(true).run(()=>watch(()=>canUseTracking(currentUser.value)?currentUser.value!.id:'',id=>{trackingAutoSave.clear();trackingSession.setOwner(id)},{immediate:true,flush:'sync'}))
