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
  <main class="login-page">
    <header class="login-header">
      <a class="brand" href="/" aria-label="股票分析首页">
        <span class="brand-mark">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17.5 9 12l3 3 7-8"/><path d="M15.5 7H19v3.5"/></svg>
        </span>
        <span><strong>股票分析</strong><small>Analysis Studio</small></span>
      </a>
      <p>行情研究与策略分析工作台</p>
    </header>

    <div class="login-layout">
      <section class="product-intro" aria-labelledby="product-title">
        <div class="intro-copy">
          <p class="eyebrow">RESEARCH WORKSPACE</p>
          <h1 id="product-title">行情、策略与公司资料，<br>在一处完成。</h1>
          <p class="intro-summary">统一管理行情观察、技术分析、策略验证与研究数据。</p>
        </div>

        <div class="market-visual" aria-hidden="true">
          <div class="visual-meta"><span>MARKET STRUCTURE</span><small>研究视图</small></div>
          <svg viewBox="0 0 720 260" preserveAspectRatio="none">
            <defs>
              <linearGradient id="line-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#0a84ff" stop-opacity=".22"/>
                <stop offset="1" stop-color="#0a84ff" stop-opacity="0"/>
              </linearGradient>
            </defs>
            <path class="grid-line" d="M0 52H720M0 104H720M0 156H720M0 208H720"/>
            <path class="area" d="M0 215C48 198 68 205 112 181S183 151 226 162s65 20 111-15 78-24 117-54 76-10 119-38 86-21 147-49V260H0Z"/>
            <path class="trend" d="M0 215C48 198 68 205 112 181S183 151 226 162s65 20 111-15 78-24 117-54 76-10 119-38 86-21 147-49"/>
            <circle cx="720" cy="26" r="4"/>
          </svg>
        </div>

        <ul class="workspace-points">
          <li><span>01</span><div><strong>市场与个股</strong><small>行情结构、技术指标与资金观察</small></div></li>
          <li><span>02</span><div><strong>策略研究</strong><small>回测、参数寻优与组合分析</small></div></li>
          <li><span>03</span><div><strong>账户数据</strong><small>个人策略与偏好安全保存</small></div></li>
        </ul>
      </section>

      <section class="auth-panel" aria-labelledby="login-title">
        <div class="auth-content">
          <div class="login-heading">
            <p class="eyebrow">{{ isSetup ? 'INITIAL SETUP' : 'ACCOUNT ACCESS' }}</p>
            <h2 id="login-title">{{ isSetup ? '创建管理员账户' : '登录账户' }}</h2>
            <p>{{ isSetup ? '首次使用，请设置应用内管理员账户。旧策略会自动归入该账户。' : '使用你的 easy-tdx 账户进入研究工作台。' }}</p>
          </div>

          <form @submit.prevent="submit">
            <label>
              <span>用户名</span>
              <input v-model.trim="username" autocomplete="username" maxlength="40" autofocus placeholder="请输入用户名" required />
            </label>
            <label>
              <span>密码</span>
              <input v-model="password" type="password" :autocomplete="isSetup ? 'new-password' : 'current-password'" minlength="8" maxlength="128" placeholder="请输入密码" required />
            </label>
            <label v-if="isSetup">
              <span>确认密码</span>
              <input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="8" maxlength="128" placeholder="再次输入密码" required />
            </label>
            <p v-if="error" class="login-error" role="alert">{{ error }}</p>
            <button class="primary login-submit" type="submit" :disabled="busy">
              <svg v-if="busy" class="button-icon spinning" viewBox="0 0 20 20"><path d="M17 10a7 7 0 1 1-2.05-4.95"/></svg>
              <span>{{ busy ? '正在验证…' : isSetup ? '创建并进入工作台' : '登录工作台' }}</span>
            </button>
          </form>

          <p class="privacy-note"><span></span>账户数据仅保存在你的 easy-tdx 服务器</p>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.login-page { display:flex; width:100%; min-height:100dvh; flex-direction:column; overflow:auto; background:#0b0c0f; }
.login-header { display:flex; height:72px; flex:0 0 72px; align-items:center; justify-content:space-between; padding:0 clamp(24px,4vw,64px); background:rgba(11,12,15,.92); border-bottom:1px solid var(--border); }
.login-header>p { color:var(--text-dim); font-size:10px; letter-spacing:.035em; }
.brand { display:flex; align-items:center; gap:11px; color:var(--text); text-decoration:none; }
.brand-mark { display:grid; width:34px; height:34px; place-items:center; color:#fff; background:#0a84ff; border-radius:9px; box-shadow:0 7px 20px rgba(10,132,255,.2),0 1px 0 rgba(255,255,255,.26) inset; }
.brand-mark svg { width:20px; }.brand-mark path { fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }
.brand strong,.brand small { display:block; }.brand strong { font-size:13px; font-weight:650; }.brand small { margin-top:1px; color:var(--text-dim); font-size:8px; letter-spacing:.06em; }
.login-layout { display:grid; min-height:calc(100dvh - 72px); flex:1; grid-template-columns:minmax(0,1fr) minmax(420px,38vw); }
.product-intro { display:flex; min-height:0; flex-direction:column; justify-content:center; padding:clamp(46px,7vh,88px) clamp(42px,8vw,128px); overflow:hidden; background:radial-gradient(circle at 15% 12%,rgba(10,132,255,.13),transparent 34%),linear-gradient(145deg,#101218,#0b0c0f 72%); }
.intro-copy { max-width:680px; animation:intro-enter .52s cubic-bezier(.2,.75,.25,1) both; }
.eyebrow { margin-bottom:10px; color:#65afff!important; font-size:9px!important; font-weight:720; letter-spacing:.16em; }
.intro-copy h1 { color:#f5f5f7; font-size:clamp(34px,4.1vw,58px); font-weight:660; line-height:1.13; letter-spacing:-.045em; }
.intro-summary { max-width:480px; margin-top:20px; color:var(--text-muted); font-size:13px; line-height:1.8; }
.market-visual { position:relative; width:min(760px,100%); height:clamp(150px,24vh,235px); margin:clamp(34px,5vh,60px) 0 26px; border-top:1px solid var(--border); border-bottom:1px solid var(--border); animation:intro-enter .52s .08s cubic-bezier(.2,.75,.25,1) both; }
.visual-meta { position:absolute; top:13px; right:2px; left:2px; z-index:1; display:flex; justify-content:space-between; color:var(--text-dim); font-size:8px; font-weight:650; letter-spacing:.12em; }.visual-meta small { font-size:9px; font-weight:500; letter-spacing:0; }
.market-visual>svg { position:absolute; inset:35px 0 0; width:100%; height:calc(100% - 35px); overflow:visible; }.grid-line { fill:none; stroke:rgba(255,255,255,.045); stroke-width:1; }.area { fill:url(#line-fill); }.trend { fill:none; stroke:#2997ff; stroke-width:2; vector-effect:non-scaling-stroke; stroke-linecap:round; stroke-dasharray:1100; animation:draw-trend 1.05s .22s ease-out both; }.market-visual circle { fill:#8ac7ff; stroke:rgba(10,132,255,.28); stroke-width:8; paint-order:stroke; animation:point-in .25s 1s ease-out both; }
.workspace-points { display:grid; width:min(760px,100%); grid-template-columns:repeat(3,1fr); list-style:none; border-top:1px solid var(--border); animation:intro-enter .52s .16s cubic-bezier(.2,.75,.25,1) both; }
.workspace-points li { display:flex; min-width:0; gap:10px; padding:18px 18px 0 0; }.workspace-points li+li { padding-left:18px; border-left:1px solid var(--border); }.workspace-points>li>span { color:#479fe9; font:9px/1.6 var(--font-mono); }.workspace-points strong,.workspace-points small { display:block; }.workspace-points strong { color:#dedee3; font-size:11px; font-weight:610; }.workspace-points small { margin-top:4px; color:var(--text-dim); font-size:9px; line-height:1.55; }
.auth-panel { display:grid; min-height:0; place-items:center; padding:48px clamp(34px,4vw,70px); background:#15161a; border-left:1px solid var(--border); }
.auth-content { width:min(360px,100%); animation:form-enter .48s .08s cubic-bezier(.2,.75,.25,1) both; }
.login-heading { margin-bottom:31px; }.login-heading h2 { font-size:28px; font-weight:670; letter-spacing:-.035em; }.login-heading>p:last-child { margin-top:9px; color:var(--text-muted); font-size:11px; line-height:1.7; }
form { display:flex; flex-direction:column; gap:17px; }label>span { display:block; margin:0 0 7px 1px; color:var(--text-muted); font-size:11px; font-weight:520; }input { min-height:44px; padding:0 12px; background:rgba(0,0,0,.22); border-radius:8px; font-size:13px; }input:focus { border-color:rgba(10,132,255,.72); box-shadow:0 0 0 3px rgba(10,132,255,.12); outline:none; }
.login-submit { position:relative; width:100%; min-height:44px; margin-top:5px; font-size:12px; }.login-submit .button-icon { position:absolute; left:14px; }.login-submit>span { line-height:1; }
.login-error { padding:9px 11px; color:#ff9b94; background:rgba(255,69,58,.08); border-left:2px solid rgba(255,86,76,.6); font-size:11px; }
.privacy-note { display:flex; align-items:center; gap:7px; margin-top:23px; color:var(--text-dim); font-size:9.5px; }.privacy-note span { width:6px; height:6px; flex:0 0 auto; background:var(--success); border-radius:50%; box-shadow:0 0 0 3px rgba(48,209,88,.08); }
@keyframes intro-enter { from{opacity:0;transform:translateY(10px)} }
@keyframes form-enter { from{opacity:0;transform:translateX(12px)} }
@keyframes draw-trend { from{stroke-dashoffset:1100} to{stroke-dashoffset:0} }
@keyframes point-in { from{opacity:0;transform:scale(.5);transform-origin:720px 26px} }
@media(max-width:900px){.login-header{height:64px;flex-basis:64px}.login-layout{min-height:calc(100dvh - 64px);grid-template-columns:1fr}.product-intro{min-height:310px;padding:42px clamp(24px,7vw,58px) 34px;justify-content:flex-start}.intro-copy h1{font-size:clamp(30px,7vw,46px)}.market-visual{height:115px;margin:28px 0 20px}.workspace-points{display:none}.auth-panel{min-height:430px;padding:46px 28px;border-top:1px solid var(--border);border-left:0}.auth-content{width:min(420px,100%)}}
@media(max-width:520px){.login-header{padding:0 20px}.login-header>p{display:none}.product-intro{min-height:250px;padding:34px 22px 24px}.intro-copy h1{font-size:30px}.intro-summary{margin-top:13px;font-size:11px}.market-visual{height:80px;margin:22px 0 0}.visual-meta{top:8px}.market-visual>svg{inset:26px 0 0;height:calc(100% - 26px)}.auth-panel{min-height:calc(100dvh - 314px);padding:38px 22px}.login-heading{margin-bottom:25px}.login-heading h2{font-size:24px}}
@media(prefers-reduced-motion:reduce){.intro-copy,.market-visual,.workspace-points,.auth-content,.trend,.market-visual circle{animation:none}}
</style>
