import { readonly, ref, watch } from 'vue'

import { fetchStockNames } from './api'
import { updatePreferences, useAuth } from './auth'
import { detectMarket } from './market'
import type { Category } from './types'

export interface StockHistoryItem {
  code: string
  name?: string
  category: Category
  startDate?: string
  endDate?: string
  usedAt: string
}

const CATEGORIES: Category[] = ['DAY', 'WEEK', 'MONTH', 'MIN_5', 'MIN_15', 'MIN_30', 'MIN_60']
const stockHistory = ref<StockHistoryItem[]>([])
const lastStock = ref<StockHistoryItem | null>(null)
const { currentUser } = useAuth()
let hydratingNames = false

function isHistoryItem(value: unknown): value is StockHistoryItem {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<StockHistoryItem>
  return typeof item.code === 'string'
    && /^\d{6}$/.test(item.code)
    && (item.name === undefined || typeof item.name === 'string')
    && CATEGORIES.includes(item.category as Category)
    && (item.startDate === undefined || typeof item.startDate === 'string')
    && (item.endDate === undefined || typeof item.endDate === 'string')
    && typeof item.usedAt === 'string'
}

watch(currentUser, (user) => {
  const saved = user?.preferences.stock_history
  const items = Array.isArray(saved) ? saved.filter(isHistoryItem).slice(0, 12) : []
  stockHistory.value = items
  const savedLastStock = user?.preferences.last_stock
  lastStock.value = isHistoryItem(savedLastStock) ? savedLastStock : (items[0] ?? null)
  void hydrateHistoryNames(items)
}, { immediate: true })

function persist(items: StockHistoryItem[], nextLastStock?: StockHistoryItem) {
  stockHistory.value = items
  if (nextLastStock) lastStock.value = nextLastStock
  void updatePreferences({
    stock_history: items,
    ...(nextLastStock ? { last_stock: nextLastStock } : {}),
  }).catch(() => undefined)
}

async function hydrateHistoryNames(items: StockHistoryItem[]) {
  const missing = items.filter((item) => !item.name)
  if (!missing.length || hydratingNames) return
  hydratingNames = true
  try {
    const unique = [...new Map(missing.map((item) => [item.code, item])).values()]
    const names = await fetchStockNames(unique.map((item) => ({
      market: detectMarket(item.code), code: item.code,
    })))
    const updated = stockHistory.value.map((item) => (
      names[item.code] ? { ...item, name: names[item.code] } : item
    ))
    if (updated.some((item, index) => item.name !== stockHistory.value[index]?.name)) persist(updated)
  } catch {
    // 名称服务不可用时保留代码，下一次账户数据刷新会自动重试。
  } finally {
    hydratingNames = false
  }
}

export function recordStockHistory(
  item: Omit<StockHistoryItem, 'usedAt'> & { usedAt?: string },
) {
  const record: StockHistoryItem = { ...item, usedAt: item.usedAt ?? new Date().toISOString() }
  const items = [
    record,
    ...stockHistory.value.filter(
      (saved) => saved.code !== record.code || saved.category !== record.category,
    ),
  ].slice(0, 12)
  persist(items, record)
  void hydrateHistoryNames(stockHistory.value)
}

export function deleteStockHistory(item: StockHistoryItem) {
  persist(stockHistory.value.filter(
    (saved) => saved.code !== item.code || saved.category !== item.category,
  ))
}

export function clearStockHistory() {
  persist([])
}

export function stockDisplayName(code: string): string {
  const clean = code.includes(':') ? code.split(':').pop()! : code
  const item = stockHistory.value.find((saved) => saved.code === clean && saved.name)
  return item?.name ? `${clean}-${item.name}` : clean
}

/** 当前登录用户最后一次成功查询的 A 股代码；旧账户自动从历史首项迁移。 */
export function getLastStockCode(fallback = '000001'): string {
  return lastStock.value?.code ?? stockHistory.value[0]?.code ?? fallback
}

export function useStockHistory() {
  return { stockHistory: readonly(stockHistory), lastStock: readonly(lastStock) }
}
