<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import { clearStockHistory, deleteStockHistory, useStockHistory } from '../stock-history'
import { detectMarket, marketLabel } from '../market'
import type { StockHistoryItem } from '../stock-history'

const emit = defineEmits<{ select: [item: StockHistoryItem] }>()
const { stockHistory } = useStockHistory()
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const menuStyle = ref<Record<string, string>>({})

function updatePosition() {
  const el = trigger.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const viewportPadding = 10
  const gap = 6
  const width = Math.min(292, window.innerWidth - viewportPadding * 2)
  const desiredHeight = 298
  const roomBelow = window.innerHeight - rect.bottom - viewportPadding
  const roomAbove = rect.top - viewportPadding
  const opensAbove = roomBelow < Math.min(desiredHeight, 190) && roomAbove > roomBelow
  const availableRoom = opensAbove ? roomAbove - gap : roomBelow - gap
  const maxHeight = Math.max(120, Math.min(desiredHeight, availableRoom, window.innerHeight - viewportPadding * 2))
  const preferredLeft = rect.right - width
  const left = Math.min(
    Math.max(viewportPadding, preferredLeft),
    window.innerWidth - width - viewportPadding,
  )
  const top = opensAbove
    ? Math.max(viewportPadding, rect.top - maxHeight - gap)
    : Math.min(rect.bottom + gap, window.innerHeight - maxHeight - viewportPadding)

  menuStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`,
    transformOrigin: opensAbove ? 'bottom right' : 'top right',
  }
}

async function toggleMenu() {
  open.value = !open.value
  if (!open.value) return
  await nextTick()
  updatePosition()
}

function choose(item: StockHistoryItem) {
  emit('select', item)
  open.value = false
}

function historyMarket(item: StockHistoryItem) {
  return marketLabel(detectMarket(item.code))
}

function historyDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric',
  }).format(date)
}

function onDocumentClick(event: MouseEvent) {
  const target = event.target as Node
  if (!root.value?.contains(target) && !menu.value?.contains(target)) open.value = false
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') open.value = false
}

function onViewportChange() {
  if (open.value) updatePosition()
}

onMounted(() => {
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
</script>

<template>
  <div ref="root" class="history-root">
    <button ref="trigger" type="button" class="history-trigger" :class="{ active: open }" :aria-expanded="open" aria-haspopup="menu" @click.stop="toggleMenu">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.2a4.8 4.8 0 1 1-4.45 3M1.8 3.7v3h3M8 5.2V8l1.9 1.15" /></svg>
      <span>股票历史</span><small v-if="stockHistory.length">{{ stockHistory.length }}</small>
      <svg class="chevron" viewBox="0 0 12 12" aria-hidden="true"><path d="m3.5 4.75 2.5 2.5 2.5-2.5" /></svg>
    </button>
    <Teleport to="body">
      <Transition name="history-menu">
      <section v-if="open" ref="menu" class="history-menu" role="menu" :style="menuStyle">
        <header><div><strong>股票历史</strong><span>最近分析过的股票</span></div><button v-if="stockHistory.length" type="button" class="clear-history" @click="clearStockHistory();open=false">清空</button></header>
        <div v-if="stockHistory.length" class="history-list">
          <div v-for="item in stockHistory" :key="`${item.code}-${item.category}`" class="history-item">
            <button type="button" class="history-select" role="menuitem" @click="choose(item)">
              <span class="history-market">{{ historyMarket(item).slice(0, 1) }}</span>
              <span class="history-copy"><strong>{{ item.code }}-{{ item.name || '名称加载中' }}</strong><small>{{ historyMarket(item) }} · {{ item.category }}</small></span>
              <time>{{ historyDate(item.usedAt) }}</time>
            </button>
            <button type="button" class="history-delete" :aria-label="`删除 ${item.code}-${item.name || ''}`" title="删除记录" @click.stop="deleteStockHistory(item)">
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 4.5h9M6 4.5V3h4v1.5M5 6.5l.45 6h5.1l.45-6" /></svg>
            </button>
          </div>
        </div>
        <div v-else class="history-empty"><span><svg viewBox="0 0 18 18"><path d="M9 3.5a5.5 5.5 0 1 1-5.1 3.45M2 3.9v3.4h3.4M9 6v3.2l2.1 1.3" /></svg></span><strong>暂无股票历史</strong><small>完成一次分析后会自动保存在这里</small></div>
      </section>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.history-root{position:relative}.history-trigger{min-height:20px;margin-top:-4px;padding:0 5px 0 6px;gap:4px;color:var(--text-dim);background:transparent;border-color:transparent;border-radius:6px;box-shadow:none;font-size:9px;line-height:1}.history-trigger:hover:not(:disabled),.history-trigger.active{color:#8ec5ff;background:rgba(10,132,255,.09);border-color:rgba(10,132,255,.15)}.history-trigger svg{width:11px;height:11px}.history-trigger svg path,.history-menu svg path{fill:none;stroke:currentColor;stroke-width:1.35;stroke-linecap:round;stroke-linejoin:round}.history-trigger small{display:grid;min-width:14px;height:14px;place-items:center;padding:0 3px;color:#b8dbff;background:rgba(10,132,255,.16);border-radius:999px;font-size:8px}.history-trigger .chevron{width:9px;transition:transform 160ms ease}.history-trigger.active .chevron{transform:rotate(180deg)}.history-menu{position:fixed;z-index:1000;display:flex;overflow:hidden;flex-direction:column;color:var(--text);background:rgba(37,39,46,.98);border:1px solid rgba(255,255,255,.13);border-radius:11px;box-shadow:0 18px 48px rgba(0,0,0,.5),0 1px 0 rgba(255,255,255,.07) inset;backdrop-filter:blur(28px) saturate(140%)}.history-menu header{display:flex;flex:0 0 auto;align-items:center;justify-content:space-between;min-height:49px;padding:9px 11px 8px 13px;border-bottom:1px solid rgba(255,255,255,.07)}.history-menu header>div{display:flex;flex-direction:column}.history-menu header strong{font-size:11px;font-weight:640}.history-menu header span{margin-top:1px;color:var(--text-dim);font-size:8px}.clear-history{min-height:23px;padding:0 7px;color:var(--text-dim);background:transparent;border-color:transparent;box-shadow:none;font-size:9px}.clear-history:hover:not(:disabled){color:#ff938c;background:rgba(255,69,58,.08);border-color:rgba(255,69,58,.12)}.history-list{min-height:0;overflow-y:auto;padding:5px}.history-item{position:relative;display:flex;align-items:center;border-radius:8px;transition:background 130ms ease}.history-item:hover{background:rgba(255,255,255,.055)}.history-select{display:grid;width:100%;min-height:48px;grid-template-columns:28px minmax(0,1fr) auto;align-items:center;gap:8px;padding:5px 34px 5px 7px;text-align:left;background:transparent;border-color:transparent;box-shadow:none}.history-select:hover:not(:disabled){background:transparent;border-color:transparent}.history-market{display:grid;width:27px;height:27px;place-items:center;color:#aed6ff;background:rgba(10,132,255,.11);border:1px solid rgba(10,132,255,.17);border-radius:7px;font-size:9px;font-weight:700}.history-copy{display:flex;min-width:0;flex-direction:column}.history-copy strong{overflow:hidden;font-size:11px;font-weight:620;line-height:1.35;text-overflow:ellipsis;white-space:nowrap}.history-copy small{margin-top:1px;color:var(--text-dim);font-size:8px}.history-select time{color:var(--text-dim);font-size:8px}.history-delete{position:absolute;right:7px;width:24px;min-height:24px;padding:0;color:transparent;background:transparent;border-color:transparent;box-shadow:none;opacity:0;transition:opacity 130ms ease,color 130ms ease,background 130ms ease}.history-item:hover .history-delete,.history-delete:focus-visible{color:var(--text-dim);opacity:1}.history-delete:hover:not(:disabled){color:#ff8d86;background:rgba(255,69,58,.09);border-color:rgba(255,69,58,.12)}.history-delete svg{width:13px;height:13px}.history-empty{display:flex;min-height:142px;align-items:center;justify-content:center;flex-direction:column;color:var(--text-dim)}.history-empty>span{display:grid;width:34px;height:34px;place-items:center;margin-bottom:9px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.065);border-radius:10px}.history-empty svg{width:17px;height:17px}.history-empty strong{color:var(--text-muted);font-size:10px;font-weight:580}.history-empty small{margin-top:3px;font-size:8px}.history-menu-enter-active,.history-menu-leave-active{transition:opacity 140ms ease,transform 170ms cubic-bezier(.2,.8,.2,1)}.history-menu-enter-from,.history-menu-leave-to{opacity:0;transform:translateY(-4px) scale(.97)}
</style>
