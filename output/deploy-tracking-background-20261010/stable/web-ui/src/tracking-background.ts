import {effectScope,watch} from 'vue'
import {useAuth} from './auth'
import {canUseTracking} from './feature-access.ts'
import {createTrackingSession} from './tracking-session.ts'

export const trackingSession=createTrackingSession()
const {currentUser}=useAuth()
// Module-level watcher survives route unmounts. Loss of access clears private
// results and prevents any in-flight result from crossing an account boundary.
effectScope(true).run(()=>watch(()=>canUseTracking(currentUser.value)?currentUser.value!.id:'',id=>trackingSession.setOwner(id),{immediate:true,flush:'sync'}))
