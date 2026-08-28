<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { changeAccountPassword, formatError } from '../api'
import { refreshCurrentUser, useAuth } from '../auth'

const { currentUser } = useAuth()
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const busy = ref(false)
const message = ref('')
const error = ref('')

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
    <section class="identity-card">
      <div class="avatar">{{ currentUser?.username.slice(0, 1).toUpperCase() }}</div>
      <div>
        <p class="eyebrow">PERSONAL DATA</p>
        <h2>{{ currentUser?.username }}</h2>
        <p>你的策略、扫描信号和偏好设置均与此账户关联。</p>
      </div>
      <span class="role" :class="currentUser?.role">{{ currentUser?.role === 'admin' ? '管理员' : '标准用户' }}</span>
    </section>

    <section class="metrics-grid">
      <article><span>已保存策略</span><strong>{{ currentUser?.saved_strategy_count ?? 0 }}</strong><small>仅你可见</small></article>
      <article><span>账户状态</span><strong class="status-text">正常</strong><small>数据持续保存</small></article>
      <article><span>上次登录</span><strong class="date-value">{{ dateText(currentUser?.last_login_at) }}</strong><small>服务器时间记录</small></article>
    </section>

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
  </div>
</template>

<style scoped>
.account-page{height:100%;overflow:auto;padding:24px;}.identity-card,.settings-card,.metrics-grid article{background:linear-gradient(145deg,rgba(39,41,48,.92),rgba(26,27,32,.94));border:1px solid var(--border);box-shadow:0 12px 30px rgba(0,0,0,.12),0 1px 0 rgba(255,255,255,.04) inset}.identity-card{display:flex;align-items:center;gap:16px;padding:22px;border-radius:14px}.avatar{display:grid;width:54px;height:54px;place-items:center;flex:0 0 auto;color:#fff;background:linear-gradient(145deg,#2997ff,#5964e8);border-radius:14px;font-size:21px;font-weight:700;box-shadow:0 8px 22px rgba(10,132,255,.24)}.identity-card h2{font-size:20px;letter-spacing:-.02em}.identity-card p:not(.eyebrow){margin-top:4px;color:var(--text-muted);font-size:11px}.eyebrow{color:#65afff;font-size:9px;font-weight:700;letter-spacing:.12em}.role{margin-left:auto;padding:5px 10px;color:var(--text-muted);background:rgba(255,255,255,.055);border:1px solid var(--border);border-radius:999px;font-size:10px}.role.admin{color:#8ac2ff;background:rgba(10,132,255,.11);border-color:rgba(10,132,255,.24)}.metrics-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:14px 0}.metrics-grid article{display:flex;min-height:112px;flex-direction:column;padding:16px;border-radius:12px}.metrics-grid span,.metrics-grid small{color:var(--text-dim);font-size:10px}.metrics-grid strong{margin:8px 0 3px;font-size:26px;letter-spacing:-.035em}.metrics-grid .status-text{color:var(--success);font-size:18px}.metrics-grid .date-value{font-size:13px;line-height:1.5}.settings-card{display:grid;grid-template-columns:minmax(220px,.75fr) minmax(320px,1.25fr);gap:44px;padding:24px;border-radius:14px}.section-copy h3{margin-top:5px;font-size:16px}.section-copy>p:last-child{margin-top:7px;color:var(--text-muted);font-size:11px;line-height:1.65}.settings-card form{display:grid;grid-template-columns:1fr 1fr;gap:13px}.settings-card label:first-child{grid-column:1/-1}.settings-card label span{display:block;margin-bottom:5px;color:var(--text-muted);font-size:10px}.settings-card input{min-height:38px}.settings-card button,.notice{grid-column:1/-1}.settings-card button{justify-self:end;min-width:130px}.notice{padding:8px 10px;border-radius:7px;font-size:10px}.notice.success{color:#8ce0a7;background:rgba(48,209,88,.09)}.notice.error{color:#ff9a93;background:rgba(255,69,58,.09)}@media(max-width:900px){.metrics-grid{grid-template-columns:1fr}.settings-card{grid-template-columns:1fr;gap:20px}}
</style>
