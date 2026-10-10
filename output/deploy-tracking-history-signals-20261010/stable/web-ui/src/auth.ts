import { readonly, ref } from 'vue'

import {
  fetchAuthStatus,
  fetchMyAccount,
  loginAccount,
  logoutAccount,
  logoutAllDevices,
  saveAccountPreferences,
  setupAdmin,
} from './api'
import type { AccountUser } from './types'

const currentUser = ref<AccountUser | null>(null)
const setupRequired = ref(false)
const ready = ref(false)
let initializing: Promise<void> | null = null
let preferenceQueue: Promise<void> = Promise.resolve()

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

export async function logoutEverywhere(): Promise<void> {
  await logoutAllDevices()
  currentUser.value = null
}

export async function refreshCurrentUser(): Promise<void> {
  const owner = currentUser.value?.id
  const user = await fetchMyAccount()
  if (currentUser.value?.id !== owner || user.id !== owner) throw new Error('登录账户已变化，请刷新页面后重试')
  currentUser.value = user
}

export function updatePreferences(patch: Record<string, unknown>): Promise<void> {
  const owner = currentUser.value?.id
  preferenceQueue = preferenceQueue.catch(() => undefined).then(async () => {
    if (!owner || currentUser.value?.id !== owner) return
    const preferences = { ...(currentUser.value?.preferences ?? {}), ...patch }
    const user = await saveAccountPreferences(preferences)
    if (currentUser.value?.id === owner) currentUser.value = user
  })
  return preferenceQueue
}

export function useAuth() {
  return {
    currentUser: readonly(currentUser),
    setupRequired: readonly(setupRequired),
    ready: readonly(ready),
  }
}

export function applyActivityAccess(owner:string,value:unknown) {
  if(currentUser.value?.id!==owner||!value||typeof value!=='object')return
  const access=value as Record<string,unknown>
  if(typeof access.tracking_allowed!=='boolean'||typeof access.active!=='boolean'||!['admin','user'].includes(String(access.role)))return
  currentUser.value={...currentUser.value,tracking_allowed:access.tracking_allowed,active:access.active,role:access.role as 'admin'|'user'}
}

export function clearExpiredActivityUser(owner:string){if(currentUser.value?.id===owner)currentUser.value=null}
