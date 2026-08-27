<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchAdminDataStatus, formatError } from '../api'

type Row = Record<string, unknown>
const capabilities = ref<Row[]>([])
const configDir = ref('')
const tdxHome = ref<string | null>(null)
const vipdoc = ref<string | null>(null)
const offline = ref<Row>({})
const loading = ref(false)
const error = ref('')

const readyCount = computed(() => capabilities.value.filter((item) => item.ready).length)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchAdminDataStatus()
    capabilities.value = data.capabilities
    configDir.value = data.config_dir
    tdxHome.value = data.tdx_home
    vipdoc.value = data.vipdoc
    offline.value = data.offline
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="data-center-page">
    <section class="status-header">
      <div><span>DATA OPERATIONS</span><h2>数据中心</h2><p>检查在线连接、扩展市场、离线行情库与持久化目录。</p></div>
      <div class="readiness"><small>可用能力</small><strong>{{ readyCount }} / {{ capabilities.length }}</strong></div>
      <button class="primary" :disabled="loading" @click="load">{{ loading ? '检测中' : '重新检测' }}</button>
    </section>
    <p v-if="error" class="error-banner status-banner">{{ error }}</p>

    <section class="capability-list">
      <article v-for="item in capabilities" :key="String(item.key)" :class="{ ready: item.ready }">
        <span class="state-icon"><svg v-if="item.ready" viewBox="0 0 20 20"><path d="m5 10 3.2 3.2L15.5 6" /></svg><svg v-else viewBox="0 0 20 20"><path d="M10 6v5M10 14.5h.01" /><circle cx="10" cy="10" r="7" /></svg></span>
        <div><h3>{{ item.name }}</h3><p>{{ item.detail }}</p></div>
        <strong>{{ item.ready ? '可用' : '待配置' }}</strong>
      </article>
    </section>

    <section class="storage-layout">
      <div class="storage-section">
        <header><div><h3>本地通达信数据</h3><p>市场强度和离线扫描依赖服务器上的 vipdoc 目录。</p></div><span :class="{ online: vipdoc }">{{ vipdoc ? 'READY' : 'OFFLINE' }}</span></header>
        <dl><div><dt>TDX_HOME</dt><dd>{{ tdxHome ?? '未设置' }}</dd></div><div><dt>vipdoc</dt><dd>{{ vipdoc ?? '未挂载' }}</dd></div><div><dt>沪市日线</dt><dd>{{ Number(offline.sh_daily_files ?? 0).toLocaleString('zh-CN') }} 个文件</dd></div><div><dt>深市日线</dt><dd>{{ Number(offline.sz_daily_files ?? 0).toLocaleString('zh-CN') }} 个文件</dd></div></dl>
        <div class="setup-note"><strong>服务器配置方式</strong><p>将通达信数据目录挂载到容器持久卷，并设置环境变量 <code>TDX_HOME</code>。未配置时，网页会保留功能入口并给出明确提示，不会返回空白结果。</p></div>
      </div>
      <div class="storage-section">
        <header><div><h3>账户与策略数据</h3><p>用户偏好、股票历史和策略库按账户保存。</p></div><span class="online">PERSISTENT</span></header>
        <dl><div><dt>数据目录</dt><dd>{{ configDir || '读取中…' }}</dd></div><div><dt>账户数据库</dt><dd>accounts.sqlite3</dd></div><div><dt>策略数据库</dt><dd>strategies.sqlite3</dd></div><div><dt>写入范围</dt><dd>容器持久卷 /data</dd></div></dl>
        <div class="setup-note secure"><strong>数据隔离</strong><p>普通用户只能读取自己的策略与偏好；数据中心和账户平台仅管理员可见。密码使用 PBKDF2-HMAC-SHA256 保存。</p></div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.data-center-page{display:flex;height:100%;min-height:0;flex-direction:column;gap:13px;overflow-y:auto}.status-header{display:flex;align-items:center;gap:14px;padding:16px 18px;background:linear-gradient(120deg,rgba(48,209,88,.07),rgba(10,132,255,.045));border:1px solid var(--border);border-radius:14px}.status-header>div:first-child{margin-right:auto}.status-header>div:first-child>span{color:#63da91;font-size:9px;font-weight:750;letter-spacing:.16em}.status-header h2{margin-top:2px;font-size:18px}.status-header p{color:var(--text-dim);font-size:10px}.readiness{padding:7px 12px;border-left:1px solid var(--border)}.readiness small{display:block;color:var(--text-dim);font-size:9px}.readiness strong{font-size:16px}.status-header button{min-height:35px}.status-banner{padding:8px 11px;border-radius:8px;font-size:11px}.capability-list{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.capability-list article{display:flex;min-width:0;align-items:center;gap:9px;padding:11px 12px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:11px}.state-icon{display:grid;width:26px;height:26px;place-items:center;flex:0 0 auto;color:#ffb340;background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.16);border-radius:7px}.ready .state-icon{color:#63da91;background:rgba(48,209,88,.08);border-color:rgba(48,209,88,.16)}.state-icon svg{width:16px}.state-icon path,.state-icon circle{fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}.capability-list article>div{min-width:0}.capability-list h3{font-size:11px}.capability-list p{overflow:hidden;color:var(--text-dim);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.capability-list article>strong{margin-left:auto;color:#ffb340;font-size:8px}.capability-list .ready>strong{color:#63da91}.storage-layout{display:grid;min-height:0;flex:1;grid-template-columns:1fr 1fr;gap:12px}.storage-section{display:flex;min-height:340px;flex-direction:column;padding:16px;background:rgba(255,255,255,.018);border:1px solid var(--border);border-radius:13px}.storage-section header{display:flex;align-items:flex-start;justify-content:space-between;padding-bottom:13px;border-bottom:1px solid var(--border)}.storage-section h3{font-size:13px}.storage-section header p{margin-top:2px;color:var(--text-dim);font-size:9px}.storage-section header>span{padding:2px 6px;color:#ffb340;background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.18);border-radius:5px;font-size:8px;font-weight:750}.storage-section header>span.online{color:#63da91;background:rgba(48,209,88,.08);border-color:rgba(48,209,88,.18)}dl{padding:6px 0}dl>div{display:grid;grid-template-columns:125px 1fr;gap:10px;padding:10px 2px;border-bottom:1px solid rgba(255,255,255,.05)}dt{color:var(--text-dim);font-size:10px}dd{overflow:hidden;color:var(--text-muted);font:10px var(--font-mono);text-align:right;text-overflow:ellipsis;white-space:nowrap}.setup-note{margin-top:auto;padding:12px;color:#d5b46f;background:rgba(255,159,10,.055);border:1px solid rgba(255,159,10,.14);border-radius:9px}.setup-note.secure{color:#8fc7ff;background:rgba(10,132,255,.055);border-color:rgba(10,132,255,.14)}.setup-note strong{font-size:10px}.setup-note p{margin-top:3px;color:var(--text-dim);font-size:9px;line-height:1.6}.setup-note code{color:inherit;font-family:var(--font-mono)}@media(max-width:1050px){.capability-list{grid-template-columns:repeat(2,1fr)}.storage-layout{grid-template-columns:1fr}.storage-section{min-height:340px}}
</style>
