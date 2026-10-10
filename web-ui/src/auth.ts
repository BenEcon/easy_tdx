import { readonly, ref, watch } from 'vue'

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
let preferenceEpoch = 0
let preferenceRevision = 0
const pendingPreferences = new Map<number, Record<string, unknown>>()
watch(() => currentUser.value?.id, () => {
  preferenceEpoch++
  pendingPreferences.clear()
  // A new account must not wait for the previous account's slow transport.
  preferenceQueue = Promise.resolve()
}, { flush: 'sync' })

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
  if (!owner) return Promise.reject(new Error('未登录，偏好未保存'))
  const epoch = preferenceEpoch, revision = ++preferenceRevision
  const trackingRevision=Object.hasOwn(patch,'tracking_groups')?String((currentUser.value?.preferences.tracking_groups as {revision?:string}|undefined)?.revision??''):undefined
  let captured: Record<string, unknown>
  try { captured = JSON.parse(JSON.stringify(patch)) } catch (e) { return Promise.reject(e) }
  pendingPreferences.set(revision, captured)
  const valid = () => currentUser.value?.id === owner && preferenceEpoch === epoch
  const operation = preferenceQueue.then(async () => {
    if (!valid()) throw new Error('登录账户已变化，旧偏好未保存')
    try {
      const user = await saveAccountPreferences(captured, owner, trackingRevision)
      if (!valid() || user.id !== owner) throw new Error('登录账户已变化，已忽略旧账户响应')
      pendingPreferences.delete(revision)
      let preferences = { ...user.preferences }
      for (const pending of pendingPreferences.values()) preferences = { ...preferences, ...pending }
      // Preference responses do not overwrite roles/access refreshed elsewhere.
      currentUser.value = { ...currentUser.value!, preferences }
    } finally {
      if (valid()) pendingPreferences.delete(revision)
    }
  })
  // Keep the internal chain fulfilled; callers still receive their own failure.
  preferenceQueue = operation.catch(() => undefined)
  return operation
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
