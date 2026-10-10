<script setup lang="ts">
// 寻优参数选择：从策略参数里勾选 1-2 个，各填取值列表（逗号分隔）。

import { computed, ref, watch } from 'vue'

import type { StrategySchema } from '../types'

const props = defineProps<{
  strategy: StrategySchema | null
  modelValue: Record<string, Array<number | string>>
}>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, Array<number | string>>] }>()

// 每个参数的取值输入框原始文本
const inputs = ref<Record<string, string>>({})

// 选中要寻优的参数
const selected = ref<Set<string>>(new Set())

function toggle(name: string) {
  if (selected.value.has(name)) {
    selected.value.delete(name)
  } else {
    if (selected.value.size >= 2) return // 最多 2 个
    selected.value.add(name)
  }
  // 触发响应式
  selected.value = new Set(selected.value)
  syncOutputs()
}

function syncOutputs() {
  const out: Record<string, Array<number | string>> = {}
  for (const name of selected.value) {
    const raw = inputs.value[name] ?? ''
    out[name] = raw
      .split(/[,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((s) => {
        const n = Number(s)
        return Number.isFinite(n) ? n : s
      })
  }
  emit('update:modelValue', out)
}

function onInput(name: string, val: string) {
  inputs.value[name] = val
  syncOutputs()
}

// 把预设取值列表格式化为输入框文本（逗号分隔）
function presetToText(vals: Array<number | string>): string {
  return vals.join(', ')
}

// 切换策略时：若有预设网格则自动勾选并填入预设取值，否则清空选择
watch(
  () => props.strategy?.name,
  () => {
    const preset = props.strategy?.preset_grid
    if (preset && Object.keys(preset).length > 0) {
      const names = Object.keys(preset)
      selected.value = new Set(names)
      const newInputs: Record<string, string> = {}
      for (const n of names) {
        newInputs[n] = presetToText(preset[n])
      }
      inputs.value = newInputs
    } else {
      selected.value = new Set()
      inputs.value = {}
    }
    syncOutputs()
  },
)

const gridPoints = computed(() => {
  const sizes = Array.from(selected.value).map((n) => {
    const raw = inputs.value[n] ?? ''
    return raw.split(/[,，\s]+/).filter((s) => s.trim()).length
  })
  return sizes.reduce((a, b) => a * b, 1)
})
</script>

<template>
  <div class="grid-picker">
    <p class="hint">
      勾选 1-2 个参数寻优，填入取值列表（逗号分隔）。
      切换策略会自动填入预设参数，可直接编辑：
    </p>
    <div v-for="p in strategy?.params" :key="p.name" class="param-row">
      <label class="check">
        <input
          type="checkbox"
          :checked="selected.has(p.name)"
          :disabled="!selected.has(p.name) && selected.size >= 2"
          @change="toggle(p.name)"
        />
        <span>{{ p.label }}（{{ p.name }}）</span>
      </label>
      <input
        v-if="selected.has(p.name)"
        :value="inputs[p.name] ?? ''"
        :placeholder="`如 ${p.default}, ${p.default}, ...`"
        class="values-input"
        @input="onInput(p.name, ($event.target as HTMLInputElement).value)"
      />
    </div>
    <p class="grid-size">网格点数：{{ gridPoints }}（上限 200）</p>
  </div>
</template>

<style scoped>
.hint {
  color: var(--text-muted);
  font-size: 12px;
  margin-bottom: 10px;
}
.param-row {
  margin-bottom: 10px;
}
.check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text);
  margin-bottom: 4px;
}
.check input[type='checkbox'] {
  width: auto;
}
.values-input {
  margin-top: 4px;
  font-family: var(--font-mono);
}
.grid-size {
  color: var(--text-dim);
  font-size: 11px;
  margin-top: 4px;
}
</style>
