<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'

const model = defineModel<T>({ required: true })

const props = withDefaults(
  defineProps<{
    options: ReadonlyArray<{
      value: T
      label: string
      description?: string
      disabled?: boolean
    }>
    placeholder?: string
    disabled?: boolean
    ariaLabel?: string
  }>(),
  {
    placeholder: '请选择',
    disabled: false,
    ariaLabel: '选择选项',
  },
)

const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const highlightedIndex = ref(-1)
const menuStyle = ref<Record<string, string>>({})
const listboxId = `mac-select-${useId()}`

const selectedIndex = computed(() => props.options.findIndex((option) => option.value === model.value))
const selectedOption = computed(() => props.options[selectedIndex.value])

function firstEnabledIndex(): number {
  return props.options.findIndex((option) => !option.disabled)
}

function lastEnabledIndex(): number {
  for (let index = props.options.length - 1; index >= 0; index -= 1) {
    if (!props.options[index]?.disabled) return index
  }
  return -1
}

function updatePosition() {
  const el = trigger.value
  if (!el) return

  const rect = el.getBoundingClientRect()
  const viewportPadding = 10
  const gap = 6
  const desiredHeight = Math.min(props.options.length * 44 + 12, 248)
  const roomBelow = window.innerHeight - rect.bottom - viewportPadding
  const roomAbove = rect.top - viewportPadding
  const opensAbove = roomBelow < Math.min(desiredHeight, 180) && roomAbove > roomBelow
  const maxHeight = Math.max(120, Math.min(desiredHeight, opensAbove ? roomAbove - gap : roomBelow - gap))
  const width = Math.max(rect.width, 176)
  const left = Math.min(Math.max(viewportPadding, rect.left), window.innerWidth - width - viewportPadding)

  menuStyle.value = {
    left: `${left}px`,
    top: opensAbove ? `${Math.max(viewportPadding, rect.top - maxHeight - gap)}px` : `${rect.bottom + gap}px`,
    width: `${width}px`,
    maxHeight: `${maxHeight}px`,
    transformOrigin: opensAbove ? 'bottom center' : 'top center',
  }
}

async function openMenu(preferredIndex = selectedIndex.value) {
  if (props.disabled || props.options.length === 0) return
  open.value = true
  highlightedIndex.value = props.options[preferredIndex]?.disabled
    ? firstEnabledIndex()
    : preferredIndex >= 0
      ? preferredIndex
      : firstEnabledIndex()
  await nextTick()
  updatePosition()
  menu.value?.querySelector<HTMLElement>('[data-highlighted="true"]')?.scrollIntoView({ block: 'nearest' })
}

function closeMenu() {
  open.value = false
  highlightedIndex.value = -1
}

function toggleMenu() {
  if (open.value) closeMenu()
  else void openMenu()
}

function selectOption(index: number) {
  const option = props.options[index]
  if (!option || option.disabled) return
  model.value = option.value
  closeMenu()
  trigger.value?.focus()
}

function stepHighlight(direction: 1 | -1) {
  if (!props.options.length) return
  let index = highlightedIndex.value
  for (let step = 0; step < props.options.length; step += 1) {
    index = (index + direction + props.options.length) % props.options.length
    if (!props.options[index]?.disabled) {
      highlightedIndex.value = index
      void nextTick(() => {
        menu.value?.querySelector<HTMLElement>('[data-highlighted="true"]')?.scrollIntoView({ block: 'nearest' })
      })
      return
    }
  }
}

function onTriggerKeydown(event: KeyboardEvent) {
  if (props.disabled) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) void openMenu()
    else stepHighlight(event.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if (event.key === 'Home' && open.value) {
    event.preventDefault()
    highlightedIndex.value = firstEnabledIndex()
    return
  }
  if (event.key === 'End' && open.value) {
    event.preventDefault()
    highlightedIndex.value = lastEnabledIndex()
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) selectOption(highlightedIndex.value)
    else void openMenu()
    return
  }
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    closeMenu()
  }
  if (event.key === 'Tab') closeMenu()
}

function onPointerDown(event: PointerEvent) {
  const target = event.target as Node
  if (trigger.value?.contains(target) || menu.value?.contains(target)) return
  closeMenu()
}

function onViewportChange() {
  if (open.value) updatePosition()
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown, true)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown, true)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
</script>

<template>
  <div class="mac-select" :class="{ open, disabled }">
    <button
      ref="trigger"
      type="button"
      class="mac-select-trigger"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="ariaLabel"
      :aria-controls="listboxId"
      :aria-expanded="open"
      :aria-activedescendant="open && highlightedIndex >= 0 ? `${listboxId}-option-${highlightedIndex}` : undefined"
      :disabled="disabled"
      @click="toggleMenu"
      @keydown="onTriggerKeydown"
    >
      <span :class="['mac-select-value', { placeholder: !selectedOption }]">
        {{ selectedOption?.label ?? placeholder }}
      </span>
      <svg class="mac-select-chevron" viewBox="0 0 12 8" aria-hidden="true">
        <path d="M1.25 1.5 6 6.25 10.75 1.5" />
      </svg>
    </button>

    <Teleport to="body">
      <Transition name="mac-menu">
        <div
          v-if="open"
          :id="listboxId"
          ref="menu"
          class="mac-select-menu"
          role="listbox"
          :aria-label="ariaLabel"
          :style="menuStyle"
        >
          <button
            v-for="(option, index) in options"
            :id="`${listboxId}-option-${index}`"
            :key="String(option.value)"
            type="button"
            class="mac-select-option"
            role="option"
            :class="{
              selected: option.value === model,
              highlighted: index === highlightedIndex,
            }"
            :aria-selected="option.value === model"
            :disabled="option.disabled"
            :data-highlighted="index === highlightedIndex"
            @mouseenter="highlightedIndex = index"
            @mousedown.prevent
            @click="selectOption(index)"
          >
            <span class="mac-select-option-copy">
              <span class="mac-select-option-label">{{ option.label }}</span>
              <span v-if="option.description" class="mac-select-option-description">
                {{ option.description }}
              </span>
            </span>
            <svg v-if="option.value === model" class="mac-select-check" viewBox="0 0 16 16" aria-hidden="true">
              <path d="m3.25 8.35 3.05 3.1 6.45-6.9" />
            </svg>
          </button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.mac-select {
  position: relative;
  width: 100%;
}

.mac-select-trigger {
  display: flex;
  width: 100%;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 9px 6px 10px;
  color: var(--text);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.018)),
    rgba(5, 6, 9, 0.52);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  box-shadow: 0 1px 0 rgba(255, 255, 255, 0.055) inset, 0 1px 2px rgba(0, 0, 0, 0.16);
  font-size: 12px;
  font-weight: 500;
  text-align: left;
  transition: border-color 150ms ease, box-shadow 150ms ease, background 150ms ease;
}

.mac-select-trigger:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.23);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.075), rgba(255, 255, 255, 0.025)),
    rgba(5, 6, 9, 0.56);
}

.mac-select-trigger:focus-visible,
.open .mac-select-trigger {
  outline: none;
  border-color: rgba(10, 132, 255, 0.92);
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.16), 0 1px 0 rgba(255, 255, 255, 0.06) inset;
}

.mac-select-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mac-select-value.placeholder { color: var(--text-dim); }

.mac-select-chevron {
  width: 10px;
  height: 7px;
  flex: 0 0 auto;
  color: var(--text-dim);
  transition: color 150ms ease, transform 180ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.mac-select-chevron path {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.open .mac-select-chevron {
  color: var(--accent-hover);
  transform: rotate(180deg);
}

.mac-select-menu {
  position: fixed;
  z-index: 1200;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 5px;
  color: var(--text);
  background:
    linear-gradient(145deg, rgba(50, 52, 60, 0.9), rgba(27, 28, 34, 0.92)),
    rgba(28, 29, 35, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 12px;
  box-shadow:
    0 22px 56px rgba(0, 0, 0, 0.48),
    0 5px 18px rgba(0, 0, 0, 0.3),
    0 1px 0 rgba(255, 255, 255, 0.1) inset;
  backdrop-filter: saturate(145%) blur(24px);
  -webkit-backdrop-filter: saturate(145%) blur(24px);
}

.mac-select-option {
  display: flex;
  width: 100%;
  min-height: 36px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 9px 7px 10px;
  color: var(--text);
  background: transparent;
  border: 0;
  border-radius: 7px;
  box-shadow: none;
  font-size: 12px;
  font-weight: 500;
  text-align: left;
  transition: background 90ms ease, color 90ms ease;
}

.mac-select-option:hover:not(:disabled),
.mac-select-option.highlighted:not(:disabled) {
  color: #fff;
  background: linear-gradient(180deg, #218dff, #0877e5);
}

.mac-select-option:active:not(:disabled) { transform: none; }

.mac-select-option.selected:not(.highlighted) {
  background: rgba(255, 255, 255, 0.065);
}

.mac-select-option-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 1px;
}

.mac-select-option-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mac-select-option-description {
  overflow: hidden;
  color: var(--text-dim);
  font-size: 10px;
  font-weight: 450;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mac-select-option.highlighted .mac-select-option-description { color: rgba(255, 255, 255, 0.72); }

.mac-select-check {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
  color: var(--accent-hover);
}

.mac-select-option.highlighted .mac-select-check { color: #fff; }

.mac-select-check path {
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.mac-menu-enter-active,
.mac-menu-leave-active {
  transition: opacity 120ms ease, transform 150ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.mac-menu-enter-from,
.mac-menu-leave-to {
  opacity: 0;
  transform: translateY(-3px) scale(0.975);
}

@media (prefers-reduced-motion: reduce) {
  .mac-select-chevron,
  .mac-menu-enter-active,
  .mac-menu-leave-active { transition-duration: 0.01ms; }
}
</style>
