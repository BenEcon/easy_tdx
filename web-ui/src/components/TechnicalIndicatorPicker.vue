<script setup lang="ts">
import { TECHNICAL_INDICATORS, type TechnicalIndicator } from '../technical-indicators'

defineProps<{ modelValue: TechnicalIndicator }>()
const emit = defineEmits<{ 'update:modelValue': [value: TechnicalIndicator] }>()
</script>

<template>
  <div class="indicator-control">
    <div class="indicator-heading">
      <span>技术指标</span>
      <small>{{ TECHNICAL_INDICATORS.find(item => item.value === modelValue)?.description }}</small>
    </div>
    <div class="indicator-options" role="radiogroup" aria-label="技术指标">
      <button
        v-for="item in TECHNICAL_INDICATORS"
        :key="item.value"
        type="button"
        role="radio"
        :aria-checked="modelValue === item.value"
        :class="{ active: modelValue === item.value }"
        @click="emit('update:modelValue', item.value)"
      >
        {{ item.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.indicator-control {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 8px;
  padding: 7px 9px 7px 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.075);
}
.indicator-heading {
  display: flex;
  min-width: 132px;
  align-items: baseline;
  gap: 8px;
  color: #a6a6ad;
  font-size: 11px;
  font-weight: 620;
}
.indicator-heading small {
  color: #5f626b;
  font-size: 9px;
  font-weight: 450;
  white-space: nowrap;
}
.indicator-options {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  background: rgba(255, 255, 255, 0.035);
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 8px;
}
.indicator-options button {
  min-height: 25px;
  padding: 0 10px;
  color: #777982;
  background: transparent;
  border-color: transparent;
  border-radius: 6px;
  box-shadow: none;
  font-size: 10px;
  font-weight: 580;
}
.indicator-options button:hover {
  color: #c8c8cd;
  background: rgba(255, 255, 255, 0.045);
  border-color: transparent;
}
.indicator-options button.active {
  color: #f5f5f7;
  background: rgba(10, 132, 255, 0.2);
  border-color: rgba(64, 158, 255, 0.35);
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.07) inset, 0 3px 10px rgba(0, 0, 0, 0.16);
}
@media (max-width: 760px) {
  .indicator-control { align-items: flex-start; flex-direction: column; gap: 7px; }
  .indicator-options { width: 100%; overflow-x: auto; }
  .indicator-options button { flex: 1 0 auto; }
}
</style>
