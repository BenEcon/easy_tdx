<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

withDefaults(
  defineProps<{
    title: string
    description?: string
  }>(),
  { description: '' },
)

const frame = ref<HTMLElement | null>(null)
const expanded = ref(false)
const fallback = ref(false)

function notifyResize() {
  void nextTick(() => {
    window.dispatchEvent(new Event('resize'))
    window.setTimeout(() => window.dispatchEvent(new Event('resize')), 180)
  })
}

async function toggleFullscreen() {
  const el = frame.value
  if (!el) return

  if (document.fullscreenElement === el) {
    await document.exitFullscreen()
    return
  }

  if (fallback.value) {
    fallback.value = false
    expanded.value = false
    document.body.classList.remove('chart-overlay-open')
    notifyResize()
    return
  }

  try {
    await el.requestFullscreen()
  } catch {
    fallback.value = true
    expanded.value = true
    document.body.classList.add('chart-overlay-open')
    notifyResize()
  }
}

function onFullscreenChange() {
  expanded.value = document.fullscreenElement === frame.value
  notifyResize()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && fallback.value) {
    fallback.value = false
    expanded.value = false
    document.body.classList.remove('chart-overlay-open')
    notifyResize()
  }
}

onMounted(() => {
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('keydown', onKeydown)
  document.body.classList.remove('chart-overlay-open')
})
</script>

<template>
  <div ref="frame" class="chart-frame" :class="{ expanded, 'fallback-expanded': fallback }">
    <header class="chart-frame-header">
      <div class="chart-frame-heading">
        <h3>{{ title }}</h3>
        <p v-if="description">{{ description }}</p>
      </div>
      <div class="chart-frame-actions">
        <slot name="actions"></slot>
        <button
          type="button"
          class="chart-expand-button"
          :aria-label="expanded ? `退出${title}全屏` : `全屏查看${title}`"
          :title="expanded ? '退出全屏（Esc）' : '全屏查看'"
          @click="toggleFullscreen"
        >
          <svg v-if="!expanded" viewBox="0 0 20 20" aria-hidden="true">
            <path d="M7.2 3.5H3.5v3.7M12.8 3.5h3.7v3.7M7.2 16.5H3.5v-3.7M12.8 16.5h3.7v-3.7" />
          </svg>
          <svg v-else viewBox="0 0 20 20" aria-hidden="true">
            <path d="M3.5 7.2h3.7V3.5M16.5 7.2h-3.7V3.5M3.5 12.8h3.7v3.7M16.5 12.8h-3.7v3.7" />
          </svg>
          <span>{{ expanded ? '退出全屏' : '全屏' }}</span>
        </button>
      </div>
    </header>
    <div class="chart-frame-content">
      <slot></slot>
    </div>
  </div>
</template>

<style scoped>
.chart-frame { width: 100%; }

.chart-frame-header {
  display: flex;
  min-height: 38px;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 10px;
}

.chart-frame-heading { min-width: 0; }
.chart-frame-heading h3 {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 620;
}
.chart-frame-heading p {
  margin-top: 3px;
  color: var(--text-dim);
  font-size: 10px;
}

.chart-frame-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
}

.chart-expand-button {
  display: inline-flex;
  min-height: 27px;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.045);
  border-color: rgba(255, 255, 255, 0.09);
  border-radius: 7px;
  box-shadow: none;
  font-size: 10px;
}
.chart-expand-button:hover:not(:disabled) {
  color: #fff;
  background: rgba(10, 132, 255, 0.13);
  border-color: rgba(10, 132, 255, 0.32);
}
.chart-expand-button svg { width: 14px; height: 14px; }
.chart-expand-button path {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.55;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.chart-frame:fullscreen,
.chart-frame.fallback-expanded {
  display: flex;
  flex-direction: column;
  padding: 18px 20px 20px;
  color: var(--text);
  background:
    radial-gradient(circle at 16% 0%, rgba(10, 132, 255, 0.08), transparent 28%),
    #0d0e12;
}

.chart-frame.fallback-expanded {
  position: fixed;
  z-index: 1600;
  inset: 0;
}

.chart-frame:fullscreen .chart-frame-header,
.chart-frame.fallback-expanded .chart-frame-header {
  min-height: 48px;
  align-items: center;
  padding: 0 0 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.075);
}

.chart-frame:fullscreen .chart-frame-heading h3,
.chart-frame.fallback-expanded .chart-frame-heading h3 {
  color: var(--text);
  font-size: 15px;
}

.chart-frame:fullscreen .chart-frame-content,
.chart-frame.fallback-expanded .chart-frame-content {
  display: flex;
  min-height: 0;
  flex: 1;
  align-items: stretch;
  padding-top: 12px;
}

.chart-frame:fullscreen .chart-frame-content :deep(.kline-chart),
.chart-frame:fullscreen .chart-frame-content :deep(.equity-chart),
.chart-frame:fullscreen .chart-frame-content :deep(.compare-chart),
.chart-frame:fullscreen .chart-frame-content :deep(.heatmap-chart),
.chart-frame:fullscreen .chart-frame-content :deep(.chanlun-chart),
.chart-frame:fullscreen .chart-frame-content :deep(.intraday-chart),
.chart-frame.fallback-expanded .chart-frame-content :deep(.kline-chart),
.chart-frame.fallback-expanded .chart-frame-content :deep(.equity-chart),
.chart-frame.fallback-expanded .chart-frame-content :deep(.compare-chart),
.chart-frame.fallback-expanded .chart-frame-content :deep(.heatmap-chart),
.chart-frame.fallback-expanded .chart-frame-content :deep(.chanlun-chart),
.chart-frame.fallback-expanded .chart-frame-content :deep(.intraday-chart) {
  height: 100% !important;
  min-height: 0;
  flex: 1;
}

@media (max-width: 760px) {
  .chart-expand-button span { display: none; }
}
</style>

<style>
body.chart-overlay-open { overflow: hidden !important; }
</style>
