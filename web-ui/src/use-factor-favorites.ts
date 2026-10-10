import {effectScope} from 'vue'
import {useAuth,updatePreferences} from './auth'
import {factorFavoriteState} from './factor-favorites'
let shared:ReturnType<typeof factorFavoriteState>|undefined
export function useFactorFavorites(){
  shared??=effectScope(true).run(()=>factorFavoriteState(useAuth().currentUser,updatePreferences))!
  return shared
}
