<script setup lang="ts">
import { computed } from 'vue'
import { confirmationPosition } from '../confirmation-replay'

const props = defineProps<{ index?: number | null; total: number; busy: boolean; label: string; phase?: string }>()
const emit = defineEmits<{ seek: [position: number] }>()
const at = computed(() => confirmationPosition(props.index, props.total))
const before = computed(() => confirmationPosition(props.index, props.total, true))
</script>

<template>
  <div v-if="at !== null" class="confirmation-replay" :aria-label="`${label}回放核验`">
    <span>{{ label }}</span>
    <button :disabled="busy || before === null" :aria-label="`${label}：回放到${phase || '确认'}前一根`" @click="before !== null && emit('seek', before)">{{ phase || '确认' }}前一根</button>
    <button :disabled="busy" :aria-label="`${label}：回放到${phase || '确认'}时刻`" @click="at !== null && emit('seek', at)">{{ phase || '确认' }}时刻</button>
  </div>
</template>

<style scoped>
.confirmation-replay { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: 8px 0 4px; font-size: 10px; }
.confirmation-replay span { color: var(--text-dim); margin-right: 2px; }
.confirmation-replay button { padding: 4px 8px; min-height: 28px; font-size: 10px; white-space: nowrap; }
.confirmation-replay button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
