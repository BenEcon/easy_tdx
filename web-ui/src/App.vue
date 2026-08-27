<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout, updatePreferences, useAuth } from './auth'

const route = useRoute()
const router = useRouter()
const { currentUser } = useAuth()
const SIDEBAR_STORAGE_KEY = 'stock-analysis.sidebar-collapsed'

function loadSidebarState(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

const sidebarCollapsed = ref(loadSidebarState())
let preferencesReady = false
let preferenceTimer: ReturnType<typeof setTimeout> | undefined

watch(currentUser, (user) => {
  if (!user) {
    preferencesReady = false
    return
  }
  const saved = user.preferences.sidebar_collapsed
  if (typeof saved === 'boolean') sidebarCollapsed.value = saved
  preferencesReady = true
}, { immediate: true })

watch(sidebarCollapsed, (value) => {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, value ? '1' : '0')
  } catch {
    // localStorage 不可用时仅不保存，不影响当前折叠状态
  }
  if (preferencesReady && currentUser.value) {
    clearTimeout(preferenceTimer)
    preferenceTimer = setTimeout(() => {
      void updatePreferences({ ...currentUser.value?.preferences, sidebar_collapsed: value })
    }, 350)
  }
})

const baseNavGroups = [
  {
    label: '分析',
    items: [
      { to: '/', label: '个股分析', paths: ['M3 16.5 8 11l3.5 3.5L18.5 7', 'M15 7h3.5v3.5'] },
      { to: '/chanlun', label: '缠论结构', paths: ['M3 16 8 9l4 5 6-9', 'M3 16h15'] },
      { to: '/signals', label: '信号雷达', paths: ['M10.5 3a7.5 7.5 0 1 1-5.3 2.2', 'M10.5 6a4.5 4.5 0 1 1-3.2 1.3', 'M10.5 10.5h.01'] },
    ],
  },
  {
    label: '研究',
    items: [
      { to: '/portfolio', label: '组合回测', paths: ['M3 4.5h6v6H3z', 'M12 4.5h6v6h-6z', 'M3 13.5h6v4H3z', 'M12 13.5h6v4h-6z'] },
      { to: '/optimize', label: '参数寻优', paths: ['M4 5h12', 'M7 3v4', 'M4 10.5h12', 'M13 8.5v4', 'M4 16h12', 'M9 14v4'] },
      { to: '/compare', label: '结果对比', paths: ['M4 5h12', 'M6 10.5h12', 'M3 16h12'] },
      { to: '/strategies', label: '策略库', paths: ['M5 3.5h10a2 2 0 0 1 2 2v12l-7-3-7 3v-12a2 2 0 0 1 2-2Z'] },
    ],
  },
  {
    label: '系统',
    items: [
      { to: '/settings', label: '行情服务器', paths: ['M10 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z', 'M16.4 12.5a7 7 0 0 0 0-5l1.4-1.1-2-3.4-1.8.7a7 7 0 0 0-4.4-2.5L9.3 3H5.4L5 5a7 7 0 0 0-2.2 3.8L1 9.5v3.9l1.8.7A7 7 0 0 0 5 17.9l.4 2h3.9l.4-2a7 7 0 0 0 4.3-2.5l1.8.7 2-3.4Z'] },
      { to: '/account', label: '个人账户', paths: ['M10.5 10a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Z', 'M4 18c.7-3.1 3-5 6.5-5s5.8 1.9 6.5 5'] },
    ],
  },
]

const navGroups = computed(() => {
  const groups = baseNavGroups.map((group) => ({ ...group, items: [...group.items] }))
  if (currentUser.value?.role === 'admin') {
    groups[groups.length - 1].items.push({
      to: '/admin/accounts',
      label: '账户管理',
      paths: ['M7.5 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z', 'M2.5 17c.5-3 2.3-4.5 5-4.5s4.5 1.5 5 4.5', 'M14.5 7.5a2 2 0 1 0 0-4', 'M14 12.5c2.5 0 4 1.4 4.4 4'],
    })
  }
  return groups
})

const pageTitle = computed(() => String(route.meta.title ?? '研究工作台'))
const pageSubtitle = computed(() => String(route.meta.subtitle ?? '行情、结构与策略验证'))
const isAuthLayout = computed(() => Boolean(route.meta.authLayout))

async function handleLogout() {
  await logout()
  await router.replace('/login')
}
</script>

<template>
  <RouterView v-if="isAuthLayout" />
  <div v-else class="app-viewport">
    <div class="app-window">
      <aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div class="sidebar-topbar">
          <div class="window-controls" aria-hidden="true">
            <span class="traffic-light close"></span>
            <span class="traffic-light minimize"></span>
            <span class="traffic-light maximize"></span>
          </div>
          <button
            type="button"
            class="sidebar-toggle"
            :aria-label="sidebarCollapsed ? '展开左侧栏' : '收起左侧栏'"
            :title="sidebarCollapsed ? '展开侧栏' : '收起侧栏'"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <rect x="2.75" y="3" width="14.5" height="14" rx="2.5" />
              <path d="M7.25 3v14" />
              <path v-if="!sidebarCollapsed" d="m12.75 7-3 3 3 3" />
              <path v-else d="m10.25 7 3 3-3 3" />
            </svg>
          </button>
        </div>

        <RouterLink class="brand" to="/" aria-label="返回股票分析">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path d="M4 17.5 9 12l3 3 7-8" />
              <path d="M15.5 7H19v3.5" />
            </svg>
          </span>
          <span class="brand-copy">
            <strong>股票分析</strong>
            <small>Analysis Studio</small>
          </span>
        </RouterLink>

        <nav class="app-nav" aria-label="主要导航">
          <section v-for="group in navGroups" :key="group.label" class="nav-group">
            <p class="nav-label">{{ group.label }}</p>
            <RouterLink
              v-for="item in group.items"
              :key="item.to"
              :to="item.to"
              class="nav-item"
              active-class="active"
              :exact="item.to === '/'"
              :title="sidebarCollapsed ? item.label : undefined"
              :aria-label="item.label"
            >
              <span class="nav-icon" aria-hidden="true">
                <svg viewBox="0 0 21 21">
                  <path v-for="path in item.paths" :key="path" :d="path" />
                </svg>
              </span>
              <span>{{ item.label }}</span>
              <span class="nav-active-dot" aria-hidden="true"></span>
            </RouterLink>
          </section>
        </nav>

        <RouterLink class="sidebar-footer" to="/account" :title="sidebarCollapsed ? currentUser?.username : undefined">
          <span class="user-mini-avatar">{{ currentUser?.username.slice(0, 1).toUpperCase() }}</span>
          <span>
            <strong>{{ currentUser?.username }}</strong>
            <small>{{ currentUser?.role === 'admin' ? '管理员' : '个人数据已同步' }}</small>
          </span>
        </RouterLink>
      </aside>

      <section class="app-workspace">
        <header class="workspace-toolbar">
          <div class="page-heading">
            <h1>{{ pageTitle }}</h1>
            <p>{{ pageSubtitle }}</p>
          </div>
          <div class="toolbar-account">
            <RouterLink to="/account" class="account-chip">
              <span class="chip-avatar">{{ currentUser?.username.slice(0, 1).toUpperCase() }}</span>
              <span>{{ currentUser?.username }}</span>
              <small v-if="currentUser?.role === 'admin'">ADMIN</small>
            </RouterLink>
            <button class="logout-button" type="button" title="退出登录" aria-label="退出登录" @click="handleLogout">
              <svg viewBox="0 0 20 20"><path d="M8 4H4.5A1.5 1.5 0 0 0 3 5.5v9A1.5 1.5 0 0 0 4.5 16H8M12.5 6.5 16 10l-3.5 3.5M7 10h9" /></svg>
            </button>
          </div>
        </header>

        <main class="app-main">
          <RouterView v-slot="{ Component }">
            <Transition name="route" mode="out-in">
              <component :is="Component" />
            </Transition>
          </RouterView>
        </main>
      </section>
    </div>
  </div>
</template>

<style scoped>
.app-viewport {
  width: 100%;
  height: 100dvh;
  padding: 14px;
  background:
    radial-gradient(circle at 14% 0%, rgba(10, 132, 255, 0.12), transparent 31%),
    radial-gradient(circle at 92% 100%, rgba(94, 92, 230, 0.08), transparent 28%),
    #08090b;
}

.app-window {
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 780px;
  overflow: hidden;
  background: rgba(20, 21, 25, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 18px;
  box-shadow:
    0 28px 90px rgba(0, 0, 0, 0.5),
    0 1px 0 rgba(255, 255, 255, 0.06) inset;
  animation: window-enter 420ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

.app-sidebar {
  width: 224px;
  flex: 0 0 224px;
  display: flex;
  flex-direction: column;
  padding: 18px 13px 14px;
  background: rgba(34, 35, 41, 0.72);
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(34px) saturate(135%);
  transition: width 220ms cubic-bezier(0.2, 0.8, 0.2, 1), flex-basis 220ms cubic-bezier(0.2, 0.8, 0.2, 1), padding 220ms ease;
}

.app-sidebar.collapsed {
  width: 70px;
  flex-basis: 70px;
  padding-right: 9px;
  padding-left: 9px;
}

.sidebar-topbar {
  display: flex;
  height: 22px;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.window-controls {
  display: flex;
  gap: 8px;
  height: 20px;
  padding-left: 5px;
}
.sidebar-toggle {
  display: grid;
  width: 25px;
  min-height: 25px;
  place-items: center;
  flex: 0 0 auto;
  margin-top: -6px;
  padding: 0;
  color: var(--text-dim);
  background: transparent;
  border-color: transparent;
  border-radius: 7px;
  box-shadow: none;
}
.sidebar-toggle:hover:not(:disabled) {
  color: var(--text);
  background: rgba(255, 255, 255, 0.065);
  border-color: rgba(255, 255, 255, 0.08);
}
.sidebar-toggle svg { width: 16px; height: 16px; }
.sidebar-toggle path,
.sidebar-toggle rect {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.35;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.collapsed .window-controls {
  gap: 4px;
  padding-left: 2px;
}
.collapsed .traffic-light { width: 7px; height: 7px; }

.traffic-light {
  position: relative;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  box-shadow: 0 0 0 0.5px rgba(0, 0, 0, 0.32) inset, 0 1px 2px rgba(0, 0, 0, 0.2);
  transition: filter 140ms ease, transform 140ms ease;
}
.window-controls:hover .traffic-light { filter: saturate(1.08) brightness(1.04); }
.traffic-light:hover { transform: scale(1.08); }
.traffic-light.close { background: #ff5f57; }
.traffic-light.minimize { background: #febc2e; }
.traffic-light.maximize { background: #28c840; }

.brand {
  display: flex;
  align-items: center;
  gap: 11px;
  margin: 14px 5px 22px;
  color: var(--text);
  text-decoration: none;
}
.collapsed .brand {
  justify-content: center;
  margin-right: 0;
  margin-left: 0;
}
.collapsed .brand-copy { display: none; }

.brand-mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  color: white;
  background: linear-gradient(145deg, #2997ff, #0066d6);
  box-shadow: 0 7px 18px rgba(10, 132, 255, 0.28), 0 1px 0 rgba(255, 255, 255, 0.35) inset;
}
.brand-mark svg {
  width: 21px;
  height: 21px;
}
.brand-mark path {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.18;
}
.brand-copy strong {
  font-size: 14px;
  font-weight: 650;
  letter-spacing: -0.01em;
}
.brand-copy small {
  margin-top: 3px;
  color: var(--text-dim);
  font-size: 10px;
  letter-spacing: 0.05em;
}

.app-nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 17px;
  min-height: 0;
  overflow-y: auto;
}

.nav-label {
  margin: 0 9px 6px;
  color: var(--text-dim);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.08em;
}
.collapsed .nav-label {
  height: 1px;
  margin: 0 7px 7px;
  overflow: hidden;
  color: transparent;
  background: rgba(255, 255, 255, 0.06);
}
.collapsed .app-nav { gap: 13px; }

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 38px;
  margin-bottom: 3px;
  padding: 0 9px 0 7px;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 10px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 12px;
  font-weight: 520;
  transition: color 150ms ease, border-color 150ms ease, background-color 150ms ease, transform 150ms ease;
}
.collapsed .nav-item {
  justify-content: center;
  padding: 0;
}
.collapsed .nav-item > span:nth-child(2) { display: none; }

.nav-item:hover {
  color: var(--text);
  border-color: rgba(255, 255, 255, 0.07);
  background: rgba(255, 255, 255, 0.05);
}

.nav-item.active {
  color: #fff;
  border-color: rgba(10, 132, 255, 0.32);
  background:
    linear-gradient(90deg, rgba(10, 132, 255, 0.18), rgba(10, 132, 255, 0.07)),
    rgba(255, 255, 255, 0.035);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.055) inset, 0 6px 18px rgba(0, 0, 0, 0.12);
}

.nav-item:active { transform: scale(0.985); }

.nav-icon {
  display: grid;
  width: 25px;
  height: 25px;
  place-items: center;
  flex: 0 0 auto;
  color: currentColor;
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.045);
  border-radius: 7px;
  transition: background 150ms ease, border-color 150ms ease, transform 150ms ease;
}
.nav-icon svg { width: 17px; height: 17px; }
.nav-icon path {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.55;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.nav-item:hover .nav-icon { transform: translateY(-1px); }
.nav-item.active .nav-icon {
  color: #8ec7ff;
  background: rgba(10, 132, 255, 0.15);
  border-color: rgba(10, 132, 255, 0.25);
}
.nav-active-dot {
  position: absolute;
  right: 7px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: transparent;
  box-shadow: none;
}
.nav-item.active .nav-active-dot {
  background: #57aaff;
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.12), 0 0 8px rgba(10, 132, 255, 0.45);
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 12px 5px 0;
  padding: 12px 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  color: var(--text-muted);
  text-decoration: none;
  border-radius: 9px;
  transition: background 150ms ease;
}
.sidebar-footer:hover { background: rgba(255, 255, 255, 0.045); }
.collapsed .sidebar-footer {
  justify-content: center;
  margin-right: 0;
  margin-left: 0;
  padding-right: 0;
  padding-left: 0;
}
.collapsed .sidebar-footer > span:last-child { display: none; }
.sidebar-footer > span:last-child {
  display: flex;
  flex-direction: column;
}
.sidebar-footer strong { font-size: 10px; font-weight: 600; }
.sidebar-footer small { margin-top: 2px; color: var(--text-dim); font-size: 9px; }
.user-mini-avatar {
  display: grid;
  width: 25px;
  height: 25px;
  place-items: center;
  flex: 0 0 auto;
  color: #dcebff;
  background: linear-gradient(145deg, rgba(10, 132, 255, 0.34), rgba(94, 92, 230, 0.3));
  border: 1px solid rgba(100, 176, 255, 0.25);
  border-radius: 7px;
  font-size: 10px;
  font-weight: 700;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 0 4px rgba(48, 209, 88, 0.1);
}

.app-workspace {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
}

.workspace-toolbar {
  height: 64px;
  flex: 0 0 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
  background: rgba(24, 25, 29, 0.84);
  border-bottom: 1px solid rgba(255, 255, 255, 0.075);
  backdrop-filter: blur(20px);
}

.page-heading h1 {
  color: var(--text);
  font-size: 14px;
  font-weight: 640;
  letter-spacing: -0.01em;
}
.page-heading p {
  margin-top: 2px;
  color: var(--text-dim);
  font-size: 10px;
}

.toolbar-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 26px;
  padding: 0 10px;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.075);
  border-radius: 999px;
  font-size: 10px;
}
.toolbar-badge span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

.toolbar-account {
  display: flex;
  align-items: center;
  gap: 7px;
}
.account-chip {
  display: flex;
  height: 30px;
  align-items: center;
  gap: 7px;
  padding: 0 9px 0 4px;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.045);
  border: 1px solid rgba(255, 255, 255, 0.075);
  border-radius: 999px;
  font-size: 10px;
  text-decoration: none;
  transition: background 150ms ease, border-color 150ms ease;
}
.account-chip:hover { background: rgba(255, 255, 255, 0.07); border-color: rgba(255, 255, 255, 0.12); }
.account-chip small { color: #72b6ff; font-size: 7px; font-weight: 750; letter-spacing: 0.08em; }
.chip-avatar {
  display: grid;
  width: 21px;
  height: 21px;
  place-items: center;
  color: #fff;
  background: linear-gradient(145deg, #2997ff, #5964e8);
  border-radius: 50%;
  font-size: 8px;
  font-weight: 700;
}
.logout-button {
  width: 30px;
  min-height: 30px;
  padding: 0;
  color: var(--text-dim);
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}
.logout-button:hover:not(:disabled) { color: #ff8e86; background: rgba(255, 69, 58, 0.08); border-color: rgba(255, 69, 58, 0.12); }
.logout-button svg { width: 15px; height: 15px; }
.logout-button path { fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; }

.app-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: var(--bg);
}

.route-enter-active,
.route-leave-active {
  transition: opacity 140ms ease, transform 180ms ease;
}
.route-enter-from { opacity: 0; transform: translateY(4px); }
.route-leave-to { opacity: 0; transform: translateY(-2px); }

@keyframes window-enter {
  from { opacity: 0; transform: translateY(8px) scale(0.992); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@media (max-width: 980px) {
  .app-viewport { padding: 0; }
  .app-window { min-width: 720px; border: 0; border-radius: 0; }
  .app-sidebar { width: 190px; flex-basis: 190px; }
}

@media (prefers-reduced-motion: reduce) {
  .app-window { animation: none; }
  .route-enter-active,
  .route-leave-active { transition: none; }
}
</style>
