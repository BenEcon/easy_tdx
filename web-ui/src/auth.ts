import { readonly, ref } from 'vue'

import {
  fetchAuthStatus,
  fetchMyAccount,
  loginAccount,
  logoutAccount,
  saveAccountPreferences,
  setupAdmin,
} from './api'
import type { AccountUser } from './types'

const currentUser = ref<AccountUser | null>(null)
const setupRequired = ref(false)
const ready = ref(false)
let initializing: Promise<void> | null = null

export async function initializeAuth(force = false): Promise<void> {
  if (ready.value && !force) return
  if (initializing) return initializing
  initializing = (async () => {
    try {
      const status = await fetchAuthStatus()
      currentUser.value = status.user
      setupRequired.value = status.setup_required
    } catch {
      currentUser.value = null
      setupRequired.value = false
    } finally {
      ready.value = true
      initializing = null
    }
  })()
  return initializing
}

export async function login(username: string, password: string): Promise<void> {
  currentUser.value = await loginAccount(username, password)
  setupRequired.value = false
}

export async function setup(username: string, password: string): Promise<void> {
  currentUser.value = await setupAdmin(username, password)
  setupRequired.value = false
}

export async function logout(): Promise<void> {
  try {
    await logoutAccount()
  } finally {
    currentUser.value = null
  }
}

export async function refreshCurrentUser(): Promise<void> {
  currentUser.value = await fetchMyAccount()
}

export async function updatePreferences(preferences: Record<string, unknown>): Promise<void> {
  currentUser.value = await saveAccountPreferences(preferences)
}

export function useAuth() {
  return {
    currentUser: readonly(currentUser),
    setupRequired: readonly(setupRequired),
    ready: readonly(ready),
  }
}
