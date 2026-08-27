<script setup lang="ts">
// 服务器设置页面：列出通达信行情服务器、测速、点选切换。
// 解决"有些 IP 能连通有些不能"的问题——不同地区/运营商对各服务器连通性不同。
import { onMounted, ref } from 'vue'
import { fetchServerHosts, testServerHosts, switchServerHost, formatError } from '../api'
import type { ServerHostInfo } from '../types'

const hosts = ref<ServerHostInfo[]>([])
const currentHost = ref('')
const loading = ref(false)
const testing = ref(false)
const switchingHost = ref<string | null>(null)
const error = ref('')
const message = ref('')

onMounted(loadHosts)

async function loadHosts() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchServerHosts()
    hosts.value = resp.hosts
    currentHost.value = resp.current_host
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

async function testAll() {
  testing.value = true
  error.value = ''
  message.value = '正在测速，请稍候...'
  try {
    const results = await testServerHosts()
    // 合并测速结果到 hosts（保留 is_current 标记）
    const latencyMap = new Map(results.map((r) => [r.host, r]))
    hosts.value = hosts.value.map((h) => {
      const tested = latencyMap.get(h.host)
      return tested
        ? { ...tested, is_current: h.is_current }
        : { ...h, latency_ms: null, reachable: false }
    })
    // 按可达+延迟排序
    hosts.value.sort((a, b) => {
      if (a.reachable !== b.reachable) return a.reachable ? -1 : 1
      return (a.latency_ms ?? 999999) - (b.latency_ms ?? 999999)
    })
    const reachable = results.filter((r) => r.reachable).length
    message.value = `测速完成：${reachable}/${results.length} 个服务器可达`
  } catch (e) {
    error.value = formatError(e)
    message.value = ''
  } finally {
    testing.value = false
  }
}

async function switchHost(host: string) {
  switchingHost.value = host
  error.value = ''
  message.value = ''
  try {
    const result = await switchServerHost(host)
    if (result.ok) {
      currentHost.value = host
      // 更新 is_current 标记
      hosts.value = hosts.value.map((h) => ({ ...h, is_current: h.host === host }))
      message.value = result.message
    } else {
      error.value = result.message
    }
  } catch (e) {
    error.value = formatError(e)
  } finally {
    switchingHost.value = null
  }
}

function latencyColor(ms: number | null): string {
  if (ms === null) return 'var(--text-dim)'
  if (ms < 100) return 'var(--green, #4caf50)'
  if (ms < 300) return 'var(--accent)'
  return 'var(--red, #f44336)'
}

function latencyText(ms: number | null): string {
  if (ms === null) return '—'
  return `${ms} ms`
}
</script>

<template>
  <div class="server-settings">
    <aside class="config-panel">
      <h2>服务器设置</h2>
      <div class="current-host">
        <span class="label">当前服务器</span>
        <span class="host-value">{{ currentHost || '未连接' }}</span>
      </div>
      <button class="btn-test" :disabled="testing || loading" @click="testAll">
        {{ testing ? '测速中...' : '🔄 测试全部服务器' }}
      </button>
      <p class="hint">
        点击"测试全部"测速各服务器延迟，然后点"使用"切换到最快或可用的服务器。
        切换后立即生效，无需重启。
      </p>
      <div v-if="message" class="message">{{ message }}</div>
      <div v-if="error" class="error-banner">⚠ {{ error }}</div>
    </aside>

    <main class="report-panel">
      <table class="host-table">
        <thead>
          <tr>
            <th>服务器 IP</th>
            <th>延迟</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="4" class="empty">加载中...</td>
          </tr>
          <tr v-else-if="hosts.length === 0">
            <td colspan="4" class="empty">暂无服务器列表</td>
          </tr>
          <tr
            v-for="h in hosts"
            :key="h.host"
            :class="{ 'is-current': h.is_current, 'is-unreachable': !h.reachable && h.latency_ms === null && testing === false && hosts.some(x => x.latency_ms !== null) }"
          >
            <td class="host-ip">{{ h.host }}</td>
            <td class="latency" :style="{ color: latencyColor(h.latency_ms) }">
              {{ testing ? '...' : latencyText(h.latency_ms) }}
            </td>
            <td>
              <span v-if="h.is_current" class="badge badge-current">当前</span>
              <span v-else-if="h.reachable" class="badge badge-ok">可达</span>
              <span v-else-if="h.latency_ms === null" class="badge badge-unknown">未测速</span>
              <span v-else class="badge badge-bad">超时</span>
            </td>
            <td>
              <button
                v-if="!h.is_current"
                class="btn-switch"
                :disabled="switchingHost !== null"
                @click="switchHost(h.host)"
              >
                {{ switchingHost === h.host ? '切换中...' : '使用' }}
              </button>
              <span v-else class="current-mark">✓</span>
            </td>
          </tr>
        </tbody>
      </table>
    </main>
  </div>
</template>

<style scoped>
.server-settings {
  display: flex;
  height: 100%;
  overflow: hidden;
}
.config-panel {
  width: 280px;
  flex-shrink: 0;
  padding: 20px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  overflow-y: auto;
}
.config-panel h2 {
  font-size: 16px;
  margin-bottom: 20px;
}
.current-host {
  margin-bottom: 16px;
}
.current-host .label {
  display: block;
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.current-host .host-value {
  font-size: 15px;
  font-weight: 600;
  font-family: monospace;
  color: var(--accent);
}
.btn-test {
  width: 100%;
  min-height: 42px;
  padding: 0 16px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  margin-bottom: 16px;
}
.btn-test:hover:not(:disabled) {
  opacity: 0.9;
}
.btn-test:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
}
.message {
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--accent-bg, rgba(0, 120, 212, 0.1));
  border-radius: var(--radius);
  font-size: 13px;
  color: var(--accent);
}
.error-banner {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(244, 67, 54, 0.1);
  border-radius: var(--radius);
  font-size: 13px;
  color: var(--red, #f44336);
}
.report-panel {
  flex: 1;
  overflow: auto;
  padding: 20px;
}
.host-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.host-table th {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 2px solid var(--border);
  color: var(--text-dim);
  font-weight: 500;
  position: sticky;
  top: 0;
  background: var(--bg-panel);
}
.host-table td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
.host-table tr.is-current {
  background: var(--accent-bg, rgba(0, 120, 212, 0.05));
}
.host-table tr.is-unreachable {
  opacity: 0.5;
}
.host-ip {
  font-family: monospace;
  font-size: 13px;
}
.latency {
  font-weight: 600;
  font-family: monospace;
}
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
}
.badge-current {
  background: var(--accent);
  color: #fff;
}
.badge-ok {
  background: rgba(76, 175, 80, 0.15);
  color: var(--green, #4caf50);
}
.badge-unknown {
  background: var(--bg-panel);
  color: var(--text-dim);
}
.badge-bad {
  background: rgba(244, 67, 54, 0.1);
  color: var(--red, #f44336);
}
.btn-switch {
  padding: 4px 16px;
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 12px;
}
.btn-switch:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}
.btn-switch:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.current-mark {
  color: var(--green, #4caf50);
  font-size: 16px;
}
.empty {
  text-align: center;
  color: var(--text-dim);
  padding: 40px;
}
</style>
