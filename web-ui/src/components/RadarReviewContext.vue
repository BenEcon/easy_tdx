<script setup lang="ts">
import type { RadarReview } from '../radar-review'
import { periodLabel } from '../period-comparison'
import { adjustmentName } from '../market-data-contract'
import { formatMarketTime } from '../bar-time'
defineProps<{ review: RadarReview | null; error: string; matches: boolean; status: string; metadata?: import('../market-data-contract').MarketDataMetadata|null }>()
</script>
<template>
  <section class="radar-review-context" aria-label="信号人工复核上下文">
    <header><div><small>信号雷达 · 原扫描记录</small><strong>{{ review ? `${review.name} · ${review.symbol}` : '无法还原复核条件' }}</strong></div><RouterLink to="/signals">返回信号雷达</RouterLink></header>
    <p v-if="error" role="alert">{{ error }}；未自动运行。</p>
    <template v-if="review">
      <dl><div><dt>扫描条件</dt><dd>{{ periodLabel(review.category) }} · {{ adjustmentName(review.adjust) }}</dd></div><div><dt>信号发生</dt><dd>{{ review.signal }} · {{ review.signalDate ? formatMarketTime(review.signalDate) : '未指定' }}</dd></div><div><dt>扫描截止</dt><dd>{{ formatMarketTime(review.asOf) }}</dd></div></dl>
      <p v-if="!matches" role="status">当前分析条件已改变，下方不再对应这条原扫描记录。</p><p v-else role="status">{{ status }}</p>
      <template v-if="review.evidence">
        <p class="review-limit">使用原任务完整行情（含预热）；原任务不可用时停止，不改取最新行情。</p>
        <template v-if="matches && metadata?.original_task?.task_id===review.evidence.taskId && metadata.original_task.row_index===review.evidence.rowIndex">
          <p class="review-limit">{{ metadata.original_task.compatible?'行情已核验，执行版本一致。':'行情已核验，执行版本已变化；后续按当前版本计算。' }}</p>
          <details><summary>来源、保存期限与执行版本</summary><p>{{ metadata.consistency_note }}</p><p>{{ metadata.original_task.storage==='memory'?'临时内存记录：服务重启或缓存淘汰后不可用。':'持久任务记录：随原任务删除，不是永久研究存档。' }}</p><p>后续分析使用当前算法及本页设置，不等于原雷达信号或原成绩重放。</p><p>{{ review.evidence.taskId }} · 条目 {{ review.evidence.rowIndex+1 }}</p><p>原版本：{{ metadata.original_task.execution_version }}</p><p>当前版本：{{ metadata.original_task.current_execution_version }}</p></details>
        </template>
      </template>
      <p v-else class="review-limit">旧扫描复核使用当前重取行情，并排除原截止后的 K 线；原扫描行情和规则版本尚未完整保存，不能视为原结果的精确重现。</p>
      <details><summary>原策略参数与行情指纹</summary><p>信号时间是策略发出时间，不等于缠论极值日期。</p><pre>{{ JSON.stringify(review.params, null, 2) }}</pre><p>{{ review.fingerprint || '原记录未提供行情指纹' }}</p></details>
    </template>
  </section>
</template>
<style scoped>
.radar-review-context{margin-bottom:18px;border-block:1px solid var(--border);padding:14px 0;min-width:0;font-size:12px}.radar-review-context header{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:center}header small{display:block;color:var(--text-muted);font-size:10px;margin-bottom:5px}header strong{font-weight:550;overflow-wrap:anywhere}header a{font-size:11px;white-space:nowrap}dl{display:flex;flex-wrap:wrap;gap:12px 28px;margin:14px 0}dt{color:var(--text-muted);font-size:10px;margin-bottom:5px}dd{margin:0;color:var(--text-dim);font-variant-numeric:tabular-nums}.radar-review-context p{font-size:11px;line-height:1.8;overflow-wrap:anywhere;margin:6px 0}.review-limit{color:var(--text-muted)}[role=alert]{color:#e6af81}summary{cursor:pointer;min-height:30px;padding-top:8px;font-size:11px;color:var(--text-dim)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;padding:10px 0}details p{color:var(--text-muted);font-family:monospace}
</style>
