<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const model = defineModel<number>({ required: true })

const props = withDefaults(
  defineProps<{
    min?: number
    max?: number
    step?: number | 'any'
    disabled?: boolean
    ariaLabel?: string
    compact?: boolean
  }>(),
  {
    step: 1,
    disabled: false,
    ariaLabel: '数值',
    compact: false,
  },
)

const draft = ref(String(model.value ?? ''))
const focused = ref(false)

watch(model, (value) => {
  if (!focused.value) draft.value = String(value ?? '')
})

const numericStep = computed(() => {
  if (props.step === 'any') {
    const source = draft.value || String(model.value ?? '')
    const fraction = source.toLowerCase().split('e')[0]?.split('.')[1]
    return fraction?.length ? 10 ** -Math.min(fraction.length, 8) : 1
  }
  const value = Number(props.step)
  return Number.isFinite(value) && value > 0 ? value : 1
})

function clamp(value: number) {
  if (props.min !== undefined) value = Math.max(props.min, value)
  if (props.max !== undefined) value = Math.min(props.max, value)
  return value
}

function decimalPlaces(value: number) {
  const text = String(value).toLowerCase()
  if (text.includes('e-')) return Number(text.split('e-')[1] ?? 0)
  return text.includes('.') ? (text.split('.')[1]?.length ?? 0) : 0
}

function normalize(value: number) {
  const precision = Math.min(10, Math.max(decimalPlaces(numericStep.value), 0))
  return Number(clamp(value).toFixed(precision))
}

function commit(raw: string) {
  draft.value = raw
  const value = Number(raw)
  if (raw.trim() === '' || raw === '-' || raw.endsWith('.') || !Number.isFinite(value)) return
  model.value = clamp(value)
}

function finishEditing() {
  focused.value = false
  const value = Number(draft.value)
  if (draft.value.trim() !== '' && Number.isFinite(value)) model.value = normalize(value)
  draft.value = String(model.value ?? '')
}

function nudge(direction: 1 | -1) {
  if (props.disabled) return
  const current = Number(draft.value)
  const base = Number.isFinite(current) ? current : Number(model.value) || 0
  const next = normalize(base + direction * numericStep.value)
  model.value = next
  draft.value = String(next)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
  event.preventDefault()
  nudge(event.key === 'ArrowUp' ? 1 : -1)
}
</script>

<template>
  <div class="number-stepper" :class="{ focused, disabled, compact }">
    <input
      :value="draft"
      type="text"
      inputmode="decimal"
      :aria-label="ariaLabel"
      :disabled="disabled"
      @focus="focused = true"
      @blur="finishEditing"
      @input="commit(($event.target as HTMLInputElement).value)"
      @keydown="onKeydown"
    />
    <div class="stepper-rail">
      <button type="button" tabindex="-1" :disabled="disabled" :aria-label="`${ariaLabel}增加`" @mousedown.prevent @click="nudge(1)">
        <svg viewBox="0 0 12 8"><path d="m2 5.5 4-3 4 3" /></svg>
      </button>
      <button type="button" tabindex="-1" :disabled="disabled" :aria-label="`${ariaLabel}减少`" @mousedown.prevent @click="nudge(-1)">
        <svg viewBox="0 0 12 8"><path d="m2 2.5 4 3 4-3" /></svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.number-stepper{display:grid;width:100%;min-height:34px;grid-template-columns:minmax(0,1fr) 27px;overflow:hidden;background:rgba(0,0,0,.2);border:1px solid var(--border-strong);border-radius:8px;box-shadow:0 1px 1px rgba(0,0,0,.16) inset;transition:border-color 150ms ease,box-shadow 150ms ease,background 150ms ease}.number-stepper:hover:not(.disabled){border-color:rgba(255,255,255,.21);background:rgba(0,0,0,.24)}.number-stepper.focused{border-color:rgba(10,132,255,.78);box-shadow:0 0 0 3px rgba(10,132,255,.12),0 1px 1px rgba(0,0,0,.16) inset}.number-stepper.disabled{opacity:.48}.number-stepper input{width:100%;min-width:0;min-height:32px;padding:5px 9px;color:var(--text);background:transparent;border:0;border-radius:0;box-shadow:none;font-size:12px;font-variant-numeric:tabular-nums;outline:0}.stepper-rail{display:grid;grid-template-rows:1fr 1fr;border-left:1px solid rgba(255,255,255,.085);background:rgba(255,255,255,.025)}.stepper-rail button{display:grid;width:100%;min-height:0;padding:0;place-items:center;color:#656973;background:transparent;border:0;border-radius:0;box-shadow:none}.stepper-rail button:first-child{border-bottom:1px solid rgba(255,255,255,.07)}.stepper-rail button:hover:not(:disabled){color:#a9d3ff;background:rgba(10,132,255,.12)}.stepper-rail button:active:not(:disabled){transform:none;background:rgba(10,132,255,.18)}.stepper-rail svg{width:9px;height:6px}.stepper-rail path{fill:none;stroke:currentColor;stroke-width:1.35;stroke-linecap:round;stroke-linejoin:round}.number-stepper.compact{min-height:30px;grid-template-columns:minmax(0,1fr) 24px;border-radius:7px}.number-stepper.compact input{min-height:28px;padding:3px 7px;text-align:right;font-size:10px}
</style>
