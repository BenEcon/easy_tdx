<script setup lang="ts">
// 投资大师名言轮播：用于后台 Task 等待期间，让用户不枯燥、还能学到东西。
// - mount 时 Fisher–Yates 洗牌，取第 0 条
// - 每 `interval` ms 推进下一条；一轮结束重新洗牌，避免短期重复
// - unmount 清 setInterval，防泄漏

import { onMounted, onUnmounted, ref } from 'vue'
import { INVESTMENT_QUOTES, type InvestmentQuote } from '../data/investment-quotes'

const props = withDefaults(
  defineProps<{
    /** 切换间隔（毫秒），默认 3000ms。 */
    interval?: number
  }>(),
  { interval: 3000 },
)

// 洗牌后的队列（不污染源数据）
const queue = ref<InvestmentQuote[]>([])
const index = ref(0)
const current = ref<InvestmentQuote>(INVESTMENT_QUOTES[0])
let timer: number | null = null

// Fisher–Yates 洗牌：返回新数组
function shuffle(arr: readonly InvestmentQuote[]): InvestmentQuote[] {
  const a = arr.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

function advance() {
  const next = index.value + 1
  if (next < queue.value.length) {
    index.value = next
  } else {
    // 一轮播完，重新洗牌，避免短期重复
    queue.value = shuffle(INVESTMENT_QUOTES)
    index.value = 0
  }
  current.value = queue.value[index.value]
}

onMounted(() => {
  queue.value = shuffle(INVESTMENT_QUOTES)
  index.value = 0
  current.value = queue.value[0]
  timer = window.setInterval(advance, props.interval)
})

onUnmounted(() => {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
})
</script>

<template>
  <div class="quote-carousel" :style="{ '--quote-interval': `${interval}ms` }">
    <div class="quote-card">
      <!-- 顶部进度条：3 秒线性循环，暗示"还在跑" -->
      <div class="quote-progress"><span class="bar" /></div>

      <div class="quote-mark">"</div>

      <Transition name="quote-fade" mode="out-in">
        <blockquote :key="current.text" class="quote-block">
          <p class="quote-text">{{ current.text }}</p>
          <footer class="quote-author">— {{ current.author }}</footer>
        </blockquote>
      </Transition>

      <p class="quote-hint">
        <span class="dot" />
        后台寻优进行中，大师智慧伴你等待…
      </p>
    </div>
  </div>
</template>

<style scoped>
.quote-carousel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  padding: 32px 16px;
  height: 100%;
}

.quote-card {
  position: relative;
  max-width: 560px;
  width: 100%;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 40px 36px 28px;
  box-shadow:
    0 12px 40px rgba(0, 0, 0, 0.35),
    0 0 0 1px rgba(245, 158, 11, 0.08);
  overflow: hidden;
}

/* 顶部进度条 */
.quote-progress {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: rgba(255, 255, 255, 0.05);
}
.quote-progress .bar {
  display: block;
  height: 100%;
  width: 100%;
  background: linear-gradient(90deg, #f59e0b, #ea580c);
  transform-origin: left center;
  animation: quote-progress-fill var(--quote-interval, 3000ms) linear infinite;
}
@keyframes quote-progress-fill {
  from { transform: scaleX(0); }
  to { transform: scaleX(1); }
}

/* 巨大引号装饰 */
.quote-mark {
  position: absolute;
  top: 8px;
  left: 18px;
  font-size: 64px;
  font-family: Georgia, 'Times New Roman', serif;
  line-height: 1;
  color: rgba(245, 158, 11, 0.18);
  user-select: none;
  pointer-events: none;
}

.quote-block {
  position: relative;
  z-index: 1;
}

.quote-text {
  font-size: 18px;
  line-height: 1.7;
  color: var(--text);
  font-weight: 500;
  margin-bottom: 14px;
  /* 中英文混排更优雅 */
  font-feature-settings: 'palt';
}

.quote-author {
  font-size: 13px;
  color: #f59e0b;
  font-weight: 600;
  text-align: right;
}

.quote-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 24px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
  font-size: 12px;
  color: var(--text-dim);
}

/* 闪烁圆点：表示还在运行 */
.dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #f59e0b;
  animation: quote-pulse 1.2s ease-in-out infinite;
}
@keyframes quote-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}

/* 过渡：fade + 轻微 slide-up */
.quote-fade-enter-active,
.quote-fade-leave-active {
  transition:
    opacity 0.35s ease,
    transform 0.35s ease;
}
.quote-fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.quote-fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
