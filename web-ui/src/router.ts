import { createRouter, createWebHistory } from 'vue-router'
import { initializeAuth, useAuth } from './auth'

// 行情与公司研究 + 单/多标的回测 + 策略工具 + 账户与服务器管理。
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
    path: '/market',
    name: 'market',
    component: () => import('./views/MarketCenterView.vue'),
    meta: { title: '市场行情', subtitle: '跟踪排行、涨跌分布与盘中异动' },
  },
  {
    path: '/intraday',
    name: 'intraday',
    component: () => import('./views/IntradayResearchView.vue'),
    meta: { title: '盘中研究', subtitle: '研究分时走势、逐笔成交、指数与实时快照' },
  },
  {
    path: '/boards',
    name: 'boards',
    component: () => import('./views/BoardResearchView.vue'),
    meta: { title: '板块研究', subtitle: '观察板块强弱、成分股与个股归属' },
  },
  {
    path: '/company',
    name: 'company',
    component: () => import('./views/CompanyResearchView.vue'),
    meta: { title: '公司资料', subtitle: '集中查阅行情、资金、公告与财务报表' },
  },
  {
    path: '/extended',
    name: 'extended',
    component: () => import('./views/ExtendedMarketView.vue'),
    meta: { title: '扩展市场', subtitle: '查询港股、期货与外盘的行情、K线和逐笔成交' },
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
    path: '/quant-research',
    name: 'quant-research',
    component: () => import('./views/QuantResearchView.vue'),
    meta: { title: '量化研究', subtitle: '计算内置因子并分析组合权重、相关性与风险贡献' },
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
  {
    path: '/admin/data',
    name: 'admin-data',
    component: () => import('./views/AdminDataCenterView.vue'),
    meta: { title: '数据中心', subtitle: '检查行情连接、扩展市场、离线数据和持久化状态', requiresAdmin: true },
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
