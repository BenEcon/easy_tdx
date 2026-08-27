<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { createAccount, fetchAccounts, formatError, resetAccountPassword, updateAccount } from '../api'
import { useAuth } from '../auth'
import type { AccountUser } from '../types'

const { currentUser } = useAuth()
const users = ref<AccountUser[]>([])
const loading = ref(true)
const busyId = ref('')
const error = ref('')
const message = ref('')
const newUsername = ref('')
const newPassword = ref('')
const newRole = ref<'admin' | 'user'>('user')
const creating = ref(false)
const resetTarget = ref<AccountUser | null>(null)
const resetPassword = ref('')
const confirmDeactivate = ref<AccountUser | null>(null)

const activeCount = computed(() => users.value.filter((user) => user.active).length)
const adminCount = computed(() => users.value.filter((user) => user.role === 'admin' && user.active).length)
const dataCount = computed(() => users.value.reduce((sum, user) => sum + (user.saved_strategy_count ?? 0), 0))

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try { users.value = (await fetchAccounts()).users }
  catch (e) { error.value = formatError(e) }
  finally { loading.value = false }
}

function dateText(value: string) {
  if (!value) return '从未登录'
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

async function addUser() {
  creating.value = true; error.value = ''; message.value = ''
  try {
    const created = await createAccount(newUsername.value, newPassword.value, newRole.value)
    users.value.push(created)
    newUsername.value = ''; newPassword.value = ''; newRole.value = 'user'
    message.value = `账户 ${created.username} 已创建`
  } catch (e) { error.value = formatError(e) }
  finally { creating.value = false }
}

async function changeRole(user: AccountUser, role: 'admin' | 'user') {
  if (role === user.role) return
  busyId.value = user.id; error.value = ''
  try { Object.assign(user, await updateAccount(user.id, { role })) }
  catch (e) { error.value = formatError(e) }
  finally { busyId.value = '' }
}

async function setActive(user: AccountUser, active: boolean) {
  busyId.value = user.id; error.value = ''
  try { Object.assign(user, await updateAccount(user.id, { active })); confirmDeactivate.value = null }
  catch (e) { error.value = formatError(e) }
  finally { busyId.value = '' }
}

async function submitReset() {
  if (!resetTarget.value) return
  busyId.value = resetTarget.value.id; error.value = ''; message.value = ''
  try {
    await resetAccountPassword(resetTarget.value.id, resetPassword.value)
    message.value = `${resetTarget.value.username} 的密码已重置，旧会话已退出`
    resetTarget.value = null; resetPassword.value = ''
  } catch (e) { error.value = formatError(e) }
  finally { busyId.value = '' }
}
</script>

<template>
  <div class="admin-page">
    <section class="summary-strip">
      <div><span>全部账户</span><strong>{{ users.length }}</strong></div>
      <div><span>当前启用</span><strong>{{ activeCount }}</strong></div>
      <div><span>管理员</span><strong>{{ adminCount }}</strong></div>
      <div><span>用户策略</span><strong>{{ dataCount }}</strong></div>
      <p><i></i>账户数据独立隔离</p>
    </section>

    <div class="admin-layout">
      <aside class="create-panel">
        <p class="eyebrow">NEW ACCOUNT</p><h2>添加账户</h2>
        <p class="intro">为每位使用者创建独立空间，策略和个人设置不会互相覆盖。</p>
        <form @submit.prevent="addUser">
          <label><span>用户名</span><input v-model.trim="newUsername" autocomplete="off" maxlength="40" placeholder="例如 bowen" required /></label>
          <label><span>初始密码</span><input v-model="newPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" placeholder="至少 8 位" required /></label>
          <label><span>账户角色</span><select v-model="newRole"><option value="user">标准用户</option><option value="admin">管理员</option></select></label>
          <button class="primary" type="submit" :disabled="creating">{{ creating ? '正在创建…' : '创建账户' }}</button>
        </form>
        <div class="permission-note"><strong>权限说明</strong><p>管理员可维护全部账户；标准用户只能访问自己的策略和设置。</p></div>
      </aside>

      <main class="accounts-panel">
        <div class="panel-heading"><div><p class="eyebrow">MEMBERS</p><h2>账户列表</h2></div><button class="sm" :disabled="loading" @click="load">刷新</button></div>
        <p v-if="message" class="banner success">{{ message }}</p><p v-if="error" class="banner error">{{ error }}</p>
        <div v-if="loading" class="empty">正在读取账户…</div>
        <div v-else class="account-list">
          <article v-for="user in users" :key="user.id" :class="{ inactive: !user.active }">
            <div class="user-avatar">{{ user.username.slice(0,1).toUpperCase() }}</div>
            <div class="user-main"><div class="name-line"><strong>{{ user.username }}</strong><span v-if="user.id === currentUser?.id">当前账户</span><span v-if="!user.active" class="off">已停用</span></div><small>上次登录 · {{ dateText(user.last_login_at) }}</small></div>
            <div class="data-cell"><strong>{{ user.saved_strategy_count ?? 0 }}</strong><span>已保存策略</span></div>
            <select :value="user.role" :disabled="busyId === user.id || !user.active" aria-label="账户角色" @change="changeRole(user, ($event.target as HTMLSelectElement).value as 'admin' | 'user')"><option value="user">标准用户</option><option value="admin">管理员</option></select>
            <div class="actions"><button class="sm" :disabled="busyId === user.id" @click="resetTarget=user;resetPassword=''">重置密码</button><button v-if="user.active" class="sm danger" :disabled="busyId === user.id || user.id === currentUser?.id" @click="confirmDeactivate=user">停用</button><button v-else class="sm" :disabled="busyId === user.id" @click="setActive(user,true)">启用</button></div>
          </article>
          <div v-if="users.length === 0" class="empty">暂无账户</div>
        </div>
      </main>
    </div>

    <div v-if="resetTarget" class="modal-backdrop" @click.self="resetTarget=null"><form class="modal" @submit.prevent="submitReset"><p class="eyebrow">PASSWORD RESET</p><h3>重置 {{ resetTarget.username }} 的密码</h3><p>保存后该账户的所有现有登录会话都会退出。</p><label><span>新密码</span><input v-model="resetPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" autofocus required /></label><div class="modal-actions"><button type="button" @click="resetTarget=null">取消</button><button class="primary" type="submit" :disabled="busyId === resetTarget.id">确认重置</button></div></form></div>
    <div v-if="confirmDeactivate" class="modal-backdrop" @click.self="confirmDeactivate=null"><section class="modal"><p class="eyebrow warning">DEACTIVATE</p><h3>停用 {{ confirmDeactivate.username }}？</h3><p>该用户将立即退出且不能登录，已保存数据会完整保留，之后可随时重新启用。</p><div class="modal-actions"><button @click="confirmDeactivate=null">取消</button><button class="danger-solid" :disabled="busyId === confirmDeactivate.id" @click="setActive(confirmDeactivate,false)">确认停用</button></div></section></div>
  </div>
</template>

<style scoped>
.admin-page{height:100%;overflow:auto;padding:18px}.summary-strip{display:flex;align-items:stretch;min-height:76px;margin-bottom:14px;padding:12px 16px;background:linear-gradient(145deg,rgba(39,41,48,.92),rgba(26,27,32,.94));border:1px solid var(--border);border-radius:13px;box-shadow:0 1px 0 rgba(255,255,255,.04) inset}.summary-strip>div{display:flex;min-width:110px;flex-direction:column;justify-content:center;padding:0 20px;border-right:1px solid var(--border)}.summary-strip>div:first-child{padding-left:3px}.summary-strip span{color:var(--text-dim);font-size:9px}.summary-strip strong{margin-top:3px;font-size:21px}.summary-strip>p{display:flex;align-items:center;gap:8px;margin-left:auto;color:var(--text-muted);font-size:10px}.summary-strip i{width:7px;height:7px;background:var(--success);border-radius:50%;box-shadow:0 0 0 4px rgba(48,209,88,.08)}.admin-layout{display:grid;grid-template-columns:270px minmax(600px,1fr);gap:14px;min-height:calc(100% - 90px)}.create-panel,.accounts-panel{background:var(--bg-panel);border:1px solid var(--border);border-radius:13px}.create-panel{padding:20px}.eyebrow{color:#65afff;font-size:9px;font-weight:700;letter-spacing:.12em}.create-panel h2,.panel-heading h2{margin-top:3px;font-size:16px}.intro{margin:7px 0 20px;color:var(--text-muted);font-size:10px;line-height:1.65}.create-panel form{display:flex;flex-direction:column;gap:13px}.create-panel label span,.modal label span{display:block;margin-bottom:5px;color:var(--text-muted);font-size:10px}.create-panel input,.create-panel select,.modal input{min-height:38px}.create-panel button{min-height:38px;margin-top:2px}.permission-note{margin-top:20px;padding:12px;background:rgba(10,132,255,.07);border:1px solid rgba(10,132,255,.13);border-radius:9px}.permission-note strong{font-size:10px}.permission-note p{margin-top:4px;color:var(--text-muted);font-size:9px;line-height:1.6}.accounts-panel{min-width:0;padding:18px}.panel-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.banner{margin-bottom:10px;padding:9px 11px;border-radius:8px;font-size:10px}.banner.success{color:#8ce0a7;background:rgba(48,209,88,.09)}.banner.error{color:#ff9a93;background:rgba(255,69,58,.09)}.account-list{display:flex;flex-direction:column;gap:8px}.account-list article{display:grid;grid-template-columns:38px minmax(130px,1fr) 80px 112px auto;align-items:center;gap:11px;padding:11px;background:rgba(255,255,255,.025);border:1px solid rgba(255,255,255,.065);border-radius:10px;transition:background .15s,border-color .15s}.account-list article:hover{background:rgba(255,255,255,.04);border-color:rgba(255,255,255,.1)}.account-list article.inactive{opacity:.58}.user-avatar{display:grid;width:36px;height:36px;place-items:center;color:#dcecff;background:linear-gradient(145deg,rgba(10,132,255,.3),rgba(94,92,230,.22));border:1px solid rgba(83,164,255,.25);border-radius:9px;font-size:13px;font-weight:700}.name-line{display:flex;align-items:center;gap:6px}.name-line strong{font-size:12px}.name-line span{padding:2px 5px;color:#8ac2ff;background:rgba(10,132,255,.1);border-radius:4px;font-size:8px}.name-line span.off{color:#ff9a93;background:rgba(255,69,58,.1)}.user-main small{display:block;margin-top:3px;color:var(--text-dim);font-size:9px}.data-cell{display:flex;flex-direction:column}.data-cell strong{font-size:14px}.data-cell span{color:var(--text-dim);font-size:8px}.account-list select{min-height:30px;font-size:10px}.actions{display:flex;gap:6px;justify-content:flex-end}.actions button{white-space:nowrap;font-size:9px}.danger{color:#ff8c84}.empty{display:grid;min-height:160px;place-items:center;color:var(--text-dim);font-size:11px}.modal-backdrop{position:fixed;z-index:100;inset:0;display:grid;place-items:center;padding:20px;background:rgba(0,0,0,.58);backdrop-filter:blur(7px)}.modal{width:min(390px,100%);padding:22px;background:linear-gradient(145deg,#272930,#1b1c21);border:1px solid rgba(255,255,255,.13);border-radius:14px;box-shadow:0 26px 80px rgba(0,0,0,.52)}.modal h3{margin:5px 0 7px;font-size:16px}.modal>p:not(.eyebrow){margin-bottom:17px;color:var(--text-muted);font-size:10px;line-height:1.6}.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.warning{color:#ff9b94}.danger-solid{color:#fff;background:linear-gradient(180deg,#ff6158,#e8423a);border-color:#ff6b63}@media(max-width:1050px){.admin-layout{grid-template-columns:240px minmax(560px,1fr)}.summary-strip>div{min-width:90px;padding:0 13px}.account-list article{grid-template-columns:36px minmax(120px,1fr) 60px 105px auto}}
</style>
