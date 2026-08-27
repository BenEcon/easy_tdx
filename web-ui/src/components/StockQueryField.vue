<script setup lang="ts">
import { computed } from 'vue'
import StockHistoryMenu from './StockHistoryMenu.vue'
import { detectMarket, marketLabel } from '../market'
import type { StockHistoryItem } from '../stock-history'
import type { Category } from '../types'

const code = defineModel<string>({ required: true })
const props = withDefaults(defineProps<{ category?: Category; label?: string }>(), {
  category: 'DAY',
  label: '股票代码',
})
const emit = defineEmits<{ historySelect: [item: StockHistoryItem] }>()
const market = computed(() => /^\d{6}$/.test(code.value) ? marketLabel(detectMarket(code.value)) : '')

function selectHistory(item: StockHistoryItem) {
  code.value = item.code
  emit('historySelect', item)
}
</script>

<template>
  <div class="stock-query-field">
    <div class="query-label"><label>{{ label }}</label><StockHistoryMenu @select="selectHistory" /></div>
    <div class="input-shell">
      <input v-model="code" maxlength="6" inputmode="numeric" autocomplete="off" placeholder="输入 6 位股票代码" />
      <span v-if="market" class="market-tag">{{ market }}</span>
    </div>
  </div>
</template>

<style scoped>
.stock-query-field{min-width:210px}.query-label{display:flex;min-height:23px;align-items:flex-start;justify-content:space-between;gap:8px}.input-shell{position:relative}.input-shell input{height:36px;padding-right:65px}.market-tag{position:absolute;right:8px;top:50%;padding:1px 6px;transform:translateY(-50%);color:var(--text-dim);background:var(--bg-elevated);border:1px solid var(--border);border-radius:5px;font-size:10px}
</style>
