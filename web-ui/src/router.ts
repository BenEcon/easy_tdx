import { createRouter, createWebHistory } from 'vue-router'
import { initializeAuth, useAuth } from './auth'

// 单标的回测（/）+ 组合回测（/portfolio）+ 参数寻优（/optimize）+ 结果对比（/compare）
// + 策略库（/strategies）+ 信号雷达（/signals）+ 服务器设置（/settings）。
const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('./views/LoginView.vue'),
    meta: { public: true, authLayout: true, title: '登录' },
  },
  {
    path: '/',
    name: 'backtest',
    component: () => import('./views/BacktestView.vue'),
    meta: { title: '个股分析', subtitle: '观察行情结构，验证策略收益与风险' },
  },
  {
    path: '/chanlun',
    name: 'chanlun',
    component: () => import('./views/ChanlunView.vue'),
    meta: { title: '缠论结构', subtitle: '识别笔、线段、中枢、买卖点与背驰' },
  },
  {
    path: '/portfolio',
    name: 'portfolio',
    component: () => import('./views/PortfolioView.vue'),
    meta: { title: '组合回测', subtitle: '在统一资金池中观察多标的组合表现' },
  },
  {
    path: '/optimize',
    name: 'optimize',
    component: () => import('./views/OptimizeView.vue'),
    meta: { title: '参数寻优', subtitle: '系统比较策略参数组合与稳定区间' },
  },
  {
    path: '/compare',
    name: 'compare',
    component: () => import('./views/CompareView.vue'),
    meta: { title: '结果对比', subtitle: '横向比较最近完成的回测任务' },
  },
  {
    path: '/strategies',
    name: 'strategies',
    component: () => import('./views/StrategiesView.vue'),
    meta: { title: '策略库', subtitle: '管理已保存策略与多策略组合' },
  },
  {
    path: '/signals',
    name: 'signals',
    component: () => import('./views/SignalRadarView.vue'),
    meta: { title: '信号雷达', subtitle: '扫描近期出现的策略信号' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('./views/ServerSettingsView.vue'),
    meta: { title: '行情服务器', subtitle: '测试连通性并切换数据节点' },
  },
  {
    path: '/account',
    name: 'account',
    component: () => import('./views/AccountView.vue'),
    meta: { title: '个人账户', subtitle: '查看账户信息并管理个人数据与安全设置' },
  },
  {
    path: '/admin/accounts',
    name: 'admin-accounts',
    component: () => import('./views/AdminAccountsView.vue'),
    meta: { title: '账户管理', subtitle: '创建账户、分配权限并查看用户数据状态', requiresAdmin: true },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  await initializeAuth()
  const { currentUser } = useAuth()
  if (to.meta.public) {
    return currentUser.value ? '/' : true
  }
  if (!currentUser.value) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && currentUser.value.role !== 'admin') return '/'
  return true
})
