<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { changeAccountPassword, formatError } from '../api'
import { logoutEverywhere, refreshCurrentUser, useAuth } from '../auth'
import BackgroundTasks from '../components/BackgroundTasks.vue'
import CloudResearchArchives from '../components/CloudResearchArchives.vue'

const { currentUser } = useAuth()
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const busy = ref(false)
const message = ref('')
const error = ref('')
const router = useRouter()
const route = useRoute()
const confirmSignOut = ref(false)
const signingOut = ref(false)
const sessionError = ref('')

async function signOutAll() {
  signingOut.value = true
  sessionError.value = ''
  try {
    await logoutEverywhere()
    await router.replace('/login')
  } catch (e) { sessionError.value = formatError(e) }
  finally { signingOut.value = false }
}

onMounted(() => refreshCurrentUser().catch(() => undefined))

function dateText(value?: string) {
  if (!value) return '尚无记录'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

async function changePassword() {
  error.value = ''
  message.value = ''
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  busy.value = true
  try {
    await changeAccountPassword(currentPassword.value, newPassword.value)
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    message.value = '密码已更新，其他设备上的登录会话已退出。'
  } catch (e) {
    error.value = formatError(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="account-page">
    <p v-if="route.query.notice==='tracking-access'" class="notice" role="status">追踪标的仅开放给管理员和已授权用户。请联系管理员开通；已有追踪数据仍保留。</p>
    <section class="identity-card">
      <div class="avatar">{{ currentUser?.username.slice(0, 1).toUpperCase() }}</div>
      <div class="identity-copy">
        <p class="eyebrow">PERSONAL DATA</p>
        <h2>{{ currentUser?.username }}</h2>
        <p>你的策略、扫描信号和偏好设置均与此账户关联。</p>
      </div>
      <span class="role" :class="currentUser?.role">{{ currentUser?.role === 'admin' ? '管理员' : '标准用户' }}</span>
    </section>

    <section class="metrics-grid" aria-label="账户概况">
      <article><span>已保存策略</span><strong>{{ currentUser?.saved_strategy_count ?? 0 }}</strong><small>仅你可见</small></article>
      <article><span>账户状态</span><strong class="status-text">正常</strong><small>数据持续保存</small></article>
      <article><span>上次登录</span><strong class="date-value">{{ dateText(currentUser?.last_login_at) }}</strong><small>服务器时间记录</small></article>
    </section>

    <CloudResearchArchives />
    <details class="activity-privacy"><summary>活动记录与隐私</summary><p>为账户安全及使用统计，系统记录登录 IP、研究查询的标的与周期，以及页面可见且近期操作时的估算活跃时长。仅管理员可查看，明细保留最近 90 天或 10 万条；不记录密码、令牌和完整查询正文。管理员查询 IP 归属地时，仅 IP 会发送至 ipwho.is，结果不代表实际所在地。</p></details>
    <section class="settings-card">
      <div class="section-copy"><p class="eyebrow">SECURITY</p><h3>修改密码</h3><p>设置新密码后，除当前浏览器外的既有会话将失效。</p></div>
      <form @submit.prevent="changePassword">
        <label><span>当前密码</span><input v-model="currentPassword" type="password" autocomplete="current-password" minlength="8" required /></label>
        <label><span>新密码</span><input v-model="newPassword" type="password" autocomplete="new-password" minlength="8" required /></label>
        <label><span>确认新密码</span><input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="8" required /></label>
        <p v-if="message" class="notice success">{{ message }}</p><p v-if="error" class="notice error">{{ error }}</p>
        <button class="primary action-button" type="submit" :disabled="busy">{{ busy ? '正在保存…' : '保存新密码' }}</button>
      </form>
    </section>
    <BackgroundTasks :key="currentUser?.id" />
    <section class="session-security" aria-labelledby="session-heading">
      <div><h3 id="session-heading">登录会话</h3><p>退出所有浏览器与设备的登录，已保存的数据不会删除。</p></div>
      <button v-if="!confirmSignOut" class="sm" @click="confirmSignOut=true">退出全部设备</button>
      <div v-else class="session-confirm">
        <p>包含当前浏览器，之后需要重新登录。确认退出？</p>
        <div><button class="sm" :disabled="signingOut" @click="confirmSignOut=false">取消</button><button class="sm" :disabled="signingOut" @click="signOutAll">{{ signingOut ? '正在退出…' : '确认退出全部' }}</button></div>
      </div>
      <p v-if="sessionError" role="alert" class="notice error">{{ sessionError }}</p>
    </section>
  </div>
</template>

<style scoped>
.activity-privacy{margin:18px 0;border-top:1px solid var(--border);padding:12px 0;color:var(--text-muted);font-size:12px}.activity-privacy summary{cursor:pointer}.activity-privacy p{margin-top:10px;line-height:1.8}
.session-security{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:18px;padding:24px 0;margin-top:16px;border-top:1px solid var(--border)}.session-security h3{font-size:15px;font-weight:600}.session-security p{margin:6px 0 0;color:var(--text-muted);font-size:12px;line-height:1.7}.session-confirm>div{display:flex;gap:8px;justify-content:flex-end;margin-top:10px}.session-security>.notice{flex-basis:100%}@media(max-width:600px){.session-security{align-items:flex-start}.session-security>button{margin-left:auto}.session-confirm{width:100%}}
.account-page { height: 100%; overflow: auto; padding: 24px; }
.identity-card { display: grid; grid-template-columns: 54px minmax(0,1fr) auto; align-items: center; gap: 16px; padding: 4px 0 24px; }
.identity-copy { min-width: 0; }
.avatar { display: grid; width: 54px; height: 54px; place-items: center; color: #fff; background: var(--accent,#2997ff); border-radius: 14px; font-size: 21px; font-weight: 700; }
.identity-card h2 { font-size: 20px; letter-spacing: -.02em; overflow-wrap: anywhere; }
.identity-card p:not(.eyebrow) { margin-top: 5px; color: var(--text-muted); font-size: 12px; line-height: 1.65; }
.eyebrow { color: #65afff; font-size: 9px; font-weight: 700; letter-spacing: .12em; }
.role { justify-self: end; padding: 5px 10px; color: var(--text-muted); background: rgba(255,255,255,.04); border-radius: 6px; font-size: 11px; line-height: 1.5; white-space: nowrap; }
.role.admin { color: #8ac2ff; background: rgba(10,132,255,.09); }
.metrics-grid { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); margin: 0 0 28px; border-block: 1px solid var(--border); }
.metrics-grid article { display: flex; min-width: 0; flex-direction: column; padding: 18px 20px; }
.metrics-grid article:first-child { padding-left: 0; }
.metrics-grid article + article { border-left: 1px solid var(--border); }
.metrics-grid span,.metrics-grid small { color: var(--text-muted); font-size: 11px; line-height: 1.6; }
.metrics-grid strong { margin: 7px 0 3px; font-size: 24px; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
.metrics-grid .status-text { color: var(--success); font-size: 18px; }
.metrics-grid .date-value { font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.settings-card { display: grid; grid-template-columns: minmax(180px,.75fr) minmax(0,1.25fr); gap: 32px; padding: 0; }
.section-copy h3 { margin-top: 5px; font-size: 15px; font-weight: 600; }
.section-copy>p:last-child { margin-top: 7px; color: var(--text-muted); font-size: 12px; line-height: 1.7; }
.settings-card form { display: grid; min-width: 0; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }
.settings-card label { min-width: 0; }
.settings-card label:first-child { grid-column: 1/-1; }
.settings-card label span { display: block; margin-bottom: 6px; color: var(--text-muted); font-size: 12px; }
.settings-card input { min-height: 38px; width: 100%; }
.settings-card button,.notice { grid-column: 1/-1; }
.settings-card button { justify-self: end; min-width: 130px; }
.notice { padding: 8px 10px; border-radius: 7px; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.notice.success { color: #8ce0a7; background: rgba(48,209,88,.09); }
.notice.error { color: #ff9a93; background: rgba(255,69,58,.09); }
@media(max-width:900px) {
  .settings-card { grid-template-columns: minmax(0,1fr); gap: 18px; }
}
@media(max-width:600px) {
  .identity-card { grid-template-columns: 42px minmax(0,1fr) auto; align-items: start; gap: 12px; padding: 8px 0 20px; }
  .avatar { width: 42px; height: 42px; border-radius: 11px; font-size: 18px; }
  .identity-card h2 { font-size: 18px; }
  .role { padding: 4px 8px; }
  .metrics-grid { grid-template-columns: repeat(2,minmax(0,1fr)); margin-bottom: 24px; }
  .metrics-grid article { padding: 14px 16px; }
  .metrics-grid article:last-child { grid-column: 1/-1; border-left: 0; border-top: 1px solid var(--border); padding-left: 0; }
  .metrics-grid .date-value { margin-top: 3px; }
}
@media(max-width:420px) {
  .settings-card form { grid-template-columns: minmax(0,1fr); }
}
</style>
