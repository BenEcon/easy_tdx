<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { formatError } from '../api'
import { login, setup, useAuth } from '../auth'

const route = useRoute()
const router = useRouter()
const { setupRequired } = useAuth()
const username = ref(setupRequired.value ? 'admin' : '')
const password = ref('')
const confirmPassword = ref('')
const busy = ref(false)
const error = ref('')

const isSetup = computed(() => setupRequired.value)

async function submit() {
  error.value = ''
  if (isSetup.value && password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  busy.value = true
  try {
    if (isSetup.value) await setup(username.value, password.value)
    else await login(username.value, password.value)
    const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(target)
  } catch (e) {
    error.value = formatError(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login-stage">
    <section class="login-window">
      <div class="login-titlebar" aria-hidden="true">
        <span class="light close"></span><span class="light minimize"></span><span class="light maximize"></span>
        <span>股票分析</span>
      </div>
      <div class="login-content">
        <div class="product-mark">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 17.5 9 12l3 3 7-8"/><path d="M15.5 7H19v3.5"/>
          </svg>
        </div>
        <div class="login-heading">
          <p class="eyebrow">ANALYSIS STUDIO</p>
          <h1>{{ isSetup ? '创建管理员账户' : '欢迎回来' }}</h1>
          <p>{{ isSetup ? '首次使用，请设置应用内管理员账户。旧策略会自动归入该账户。' : '登录后继续访问你的行情研究与策略数据。' }}</p>
        </div>

        <form @submit.prevent="submit">
          <label>
            <span>用户名</span>
            <input v-model.trim="username" autocomplete="username" maxlength="40" autofocus placeholder="输入用户名" required />
          </label>
          <label>
            <span>密码</span>
            <input v-model="password" type="password" :autocomplete="isSetup ? 'new-password' : 'current-password'" minlength="8" maxlength="128" placeholder="至少 8 位" required />
          </label>
          <label v-if="isSetup">
            <span>确认密码</span>
            <input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" placeholder="再次输入密码" required />
          </label>
          <p v-if="error" class="login-error">{{ error }}</p>
          <button class="primary login-submit" type="submit" :disabled="busy">
            <svg v-if="busy" class="button-icon spinning" viewBox="0 0 20 20"><path d="M17 10a7 7 0 1 1-2.05-4.95"/></svg>
            {{ busy ? '正在验证…' : isSetup ? '创建并进入工作台' : '登录工作台' }}
          </button>
        </form>
        <p class="privacy-note"><span></span>账户数据仅保存在你的 easy-tdx 服务器</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-stage { display:grid; width:100%; height:100dvh; place-items:center; padding:28px; overflow:auto; background:radial-gradient(circle at 20% 10%,rgba(10,132,255,.18),transparent 35%),radial-gradient(circle at 85% 85%,rgba(94,92,230,.12),transparent 30%),#08090b; }
.login-window { width:min(440px,100%); overflow:hidden; background:rgba(29,30,35,.94); border:1px solid rgba(255,255,255,.12); border-radius:18px; box-shadow:0 30px 100px rgba(0,0,0,.58),0 1px 0 rgba(255,255,255,.07) inset; backdrop-filter:blur(32px); animation:login-in .38s cubic-bezier(.2,.8,.2,1) both; }
.login-titlebar { position:relative; display:flex; align-items:center; gap:8px; height:46px; padding:0 15px; color:var(--text-dim); border-bottom:1px solid rgba(255,255,255,.07); font-size:10px; }
.login-titlebar > span:last-child { position:absolute; left:50%; transform:translateX(-50%); }
.light { width:11px; height:11px; border-radius:50%; box-shadow:0 0 0 .5px rgba(0,0,0,.35) inset; }.close{background:#ff5f57}.minimize{background:#febc2e}.maximize{background:#28c840}
.login-content { padding:34px 40px 30px; }
.product-mark { display:grid; width:48px; height:48px; place-items:center; color:#fff; background:linear-gradient(145deg,#35a3ff,#0675e7); border-radius:13px; box-shadow:0 10px 28px rgba(10,132,255,.28),0 1px 0 rgba(255,255,255,.32) inset; }
.product-mark svg { width:27px; }.product-mark path { fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.login-heading { margin:22px 0 25px; }.eyebrow { margin-bottom:6px; color:#65afff!important; font-size:9px!important; font-weight:700; letter-spacing:.13em; }.login-heading h1 { font-size:25px; font-weight:680; letter-spacing:-.035em; }.login-heading p { margin-top:8px; color:var(--text-muted); font-size:12px; line-height:1.65; }
form { display:flex; flex-direction:column; gap:14px; }label>span { display:block; margin:0 0 6px 2px; color:var(--text-muted); font-size:11px; }input { min-height:42px; padding:0 12px; background:rgba(0,0,0,.24); border-radius:9px; font-size:13px; }input:focus { border-color:rgba(10,132,255,.72); box-shadow:0 0 0 3px rgba(10,132,255,.12); outline:none; }
.login-submit { width:100%; min-height:42px; margin-top:4px; font-size:13px; }.login-error { padding:9px 11px; color:#ff9b94; background:rgba(255,69,58,.1); border:1px solid rgba(255,69,58,.2); border-radius:8px; font-size:11px; }
.privacy-note { display:flex; align-items:center; justify-content:center; gap:7px; margin-top:20px; color:var(--text-dim); font-size:10px; }.privacy-note span { width:6px; height:6px; background:var(--success); border-radius:50%; box-shadow:0 0 0 3px rgba(48,209,88,.09); }
@keyframes login-in { from{opacity:0;transform:translateY(10px) scale(.99)} }
@media(max-width:520px){.login-stage{padding:12px}.login-content{padding:28px 24px}.login-window{border-radius:15px}}
</style>
