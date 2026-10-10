<script setup lang="ts">
import type { RadarArchiveSource } from '../radar-archive'
import { periodLabel } from '../period-comparison'
import { adjustmentName } from '../market-data-contract'
import { formatMarketTime } from '../bar-time'
defineProps<{source?:RadarArchiveSource;legacyReference?:boolean}>()
</script>
<template>
  <details v-if="source" class="archived-radar" aria-label="已封存的原扫描来源">
    <summary><strong>原扫描来源</strong><span>{{ source.review.symbol }} · {{ periodLabel(source.review.category) }} · {{ source.receipt.bars.length }} 根已封存</span></summary>
    <div class="source-body">
      <p>原扫描条目、完整行情与预热区间已随本档保存；查阅不依赖原任务缓存，也不重新取数或计算。</p>
      <p class="scope">这是账户上传的来源记录，不是服务端认证凭据。以下内容是保存时的研究结果，可能采用其他周期、回放截止或新版算法，不等同于原扫描信号。</p>
      <dl><div><dt>原策略</dt><dd>{{ source.receipt.row.strategy_name }} · {{ source.receipt.row.strategy }}</dd></div><div><dt>原扫描条件</dt><dd>{{ periodLabel(source.review.category) }} · {{ adjustmentName(source.review.adjust) }} · 窗口 {{ source.receipt.window_bars }} 根</dd></div><div><dt>原扫描截止</dt><dd>{{ formatMarketTime(source.review.asOf) }}</dd></div><div><dt>本次复核选择</dt><dd>{{ source.review.signal }} · {{ source.review.signalDate ? formatMarketTime(source.review.signalDate) : '未指定时点' }}</dd></div></dl>
      <h4>原窗口内信号</h4>
      <ul v-if="source.receipt.row.recent_signals.length"><li v-for="(signal,index) in source.receipt.row.recent_signals" :key="index"><time>{{ formatMarketTime(signal.date) }}</time><span>{{ signal.direction==='BUY'?'买入':'卖出' }}</span></li></ul>
      <p v-else>原窗口内没有信号；未补算。</p>
      <details><summary>参数与来源标识</summary><pre>{{ JSON.stringify(source.review.params,null,2) }}</pre><p>原任务 {{ source.receipt.task_id }} · 条目 {{ source.receipt.row_index+1 }}</p><p>原执行版本：{{ source.receipt.execution_version }}</p><p>读取原任务时的执行版本：{{ source.receipt.current_execution_version }}</p><p>原行情指纹：{{ source.review.fingerprint }}</p><p>读取时保存方式：{{ source.receipt.storage==='memory'?'临时内存':'持久任务' }}。本档已独立保存，不据此判断原任务目前是否仍存在。</p></details>
    </div>
  </details>
  <p v-else-if="legacyReference" class="legacy-source">此旧档只留下原任务引用，未保存完整扫描条目；当前无法据此还原原策略信号。已有行情和研究结果仍保留。</p>
</template>
<style scoped>
.archived-radar{border-block:1px solid var(--border);padding:10px 0;margin:16px 0;min-width:0}summary{cursor:pointer;min-height:32px;font-size:12px;line-height:1.8;overflow-wrap:anywhere}summary strong{font-weight:550;margin-right:14px}summary span{font-size:11px;color:var(--text-muted)}summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.source-body{padding:8px 0 4px 18px;min-width:0}p,.legacy-source{font-size:11px;color:var(--text-muted);line-height:1.9;overflow-wrap:anywhere}.scope{margin-bottom:16px}dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px 24px}dt{font-size:10px;color:var(--text-muted);margin-bottom:5px}dd{margin:0;font-size:12px;line-height:1.7;overflow-wrap:anywhere}h4{font-size:12px;font-weight:550;margin:20px 0 8px}ul{list-style:none;padding:0;margin:0 0 14px;max-width:460px}li{display:flex;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px solid var(--border);font-size:11px;font-variant-numeric:tabular-nums}pre{font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere}details details{margin-top:12px}@media(max-width:600px){.source-body{padding-left:8px}dl{grid-template-columns:1fr}summary span{display:block;margin-left:16px}}
</style>
