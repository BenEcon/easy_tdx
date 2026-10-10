<script setup lang="ts">
import MacSelect from './MacSelect.vue'
import {benchmarkOptions} from '../factor-benchmark'
defineProps<{modelValue:string}>()
defineEmits<{'update:modelValue':[value:string]}>()
</script>
<template><div class="benchmark-field"><label>基准指数</label><MacSelect :model-value="modelValue" :options="benchmarkOptions" aria-label="因子基准指数" @update:model-value="$emit('update:modelValue',$event)" /><p>独立指数 · 不复权 · 同周期精确对齐，缺失不填充</p></div></template>
<style scoped>.benchmark-field{min-width:0;margin:10px 0}.benchmark-field>label{display:block;font-size:12px;color:var(--text-secondary);margin-bottom:8px}.benchmark-field>p{font-size:11px;color:var(--text-muted);line-height:1.7;margin:6px 0 0}</style>
