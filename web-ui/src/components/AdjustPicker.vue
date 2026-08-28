<script setup lang="ts">
import MacSelect from './MacSelect.vue'
import { useMarketPreferences } from '../market-preferences'

defineProps<{ compact?: boolean }>()
const { adjustMode, adjustOptions } = useMarketPreferences()
</script>

<template>
  <div class="adjust-picker" :class="{ compact }">
    <label v-if="!compact">复权方式</label>
    <MacSelect v-model="adjustMode" :options="adjustOptions" aria-label="全局复权方式" />
    <small v-if="!compact">自动应用到行情、分析与回测，并保存到当前账号</small>
  </div>
</template>

<style scoped>
.adjust-picker{display:flex;min-width:0;flex-direction:column;gap:5px}.adjust-picker label{color:var(--text-dim);font-size:11px}.adjust-picker small{color:var(--text-dim);font-size:9px;line-height:1.5}.adjust-picker.compact{width:118px}.adjust-picker.compact :deep(.mac-select-trigger){min-height:34px}
</style>
