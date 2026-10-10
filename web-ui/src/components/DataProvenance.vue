<script setup lang="ts">
import { adjustmentName, dataSourceName, type MarketDataMetadata } from '../market-data-contract'
defineProps<{ metadata: MarketDataMetadata; count?: number }>()
</script>

<template>
  <section class="data-provenance" aria-label="行情数据口径">
    <details>
      <summary><strong>数据口径</strong><span>{{ dataSourceName(metadata.source) }} · {{ adjustmentName(metadata.actual_adjust) }}</span><time v-if="metadata.last_closed_at">收盘截至 {{ metadata.last_closed_at }}</time></summary>
      <div class="provenance-content">
        <dl><div><dt>行情范围</dt><dd>{{ count == null ? '根数未记录' : `${count} 根` }} · {{ metadata.category }}</dd></div><div><dt>{{ metadata.actual_adjust === 'UNKNOWN' ? '服务端校验时间' : '采集时间' }}</dt><dd>{{ metadata.observed_at }}</dd></div><div><dt>时间标签</dt><dd>{{ metadata.bar_time === 'end' ? '周期结束时刻' : '周期开始时刻' }} · 上海时区</dd></div></dl>
        <p v-if="metadata.source_note">{{ metadata.source_note }}</p>
        <p v-if="metadata.requested_start || metadata.requested_end">请求区间 {{ metadata.requested_start ?? '未指定起点' }} — {{ metadata.requested_end ?? '未指定终点' }}</p>
        <p v-if="metadata.range_start || metadata.range_end">实际输入 {{ metadata.range_start ?? '无数据' }} — {{ metadata.range_end ?? '无数据' }}</p>
        <p>{{ metadata.completion_note }}</p><p>{{ metadata.volume_policy }}。当前采集版本不代表历史当时可得版本。</p>
        <p v-if="metadata.page_count">区间 {{ metadata.range_start ?? '无数据' }} — {{ metadata.range_end ?? '无数据' }} · {{ metadata.page_count }} 页 · 排除 {{ metadata.excluded_open_count ?? 0 }} 根未收盘柱。</p>
        <p v-if="metadata.consistency_note">{{ metadata.consistency_note }}</p>
        <p v-if="metadata.calendar_version">交易日历 {{ metadata.calendar_version }}；停牌状态未独立核验。</p>
        <p v-if="metadata.data_fingerprint" class="data-fingerprint">数据指纹 <code>{{ metadata.data_fingerprint }}</code></p>
        <p v-for="message in metadata.collection_quality?.warnings ?? []" :key="message">采集范围提示：{{ message }}</p>
        <slot />
      </div>
    </details>
    <p v-if="metadata.actual_adjust === 'UNKNOWN'" class="data-warning">输入价格已校验；{{ adjustmentName(metadata.requested_adjust) }}为请求声明，不能据此证明数据已按该方式复权。</p>
    <p v-else-if="metadata.actual_adjust !== metadata.requested_adjust" class="data-warning" role="alert">复权口径不一致：请求 {{ adjustmentName(metadata.requested_adjust) }}，实际 {{ adjustmentName(metadata.actual_adjust) }}。</p>
    <p v-for="message in metadata.quality?.errors ?? []" :key="message" class="data-warning" role="alert">{{ message }}</p>
    <p v-for="message in metadata.quality?.warnings ?? []" :key="message" class="data-warning">{{ message }}</p>
  </section>
</template>

<style scoped>
.data-provenance{border-bottom:1px solid var(--border);padding:10px 0;color:var(--text-dim);font-size:12px;min-width:0}.data-provenance summary{display:flex;align-items:center;flex-wrap:wrap;gap:8px 18px;cursor:pointer;min-height:32px;list-style:none;transition:color .15s}.data-provenance summary:before{content:'›';color:var(--text-muted);transition:transform .15s}.data-provenance details[open]>summary:before{transform:rotate(90deg)}.data-provenance summary:hover{color:var(--text)}.data-provenance strong{color:var(--text);font-weight:500}.data-provenance time{margin-left:auto;font-size:11px;font-variant-numeric:tabular-nums}.provenance-content{padding:8px 0 4px 22px}.provenance-content dl{display:flex;flex-wrap:wrap;gap:12px 28px;margin:8px 0}.provenance-content dt{color:var(--text-muted);font-size:11px}.provenance-content dd{margin:4px 0 0}.provenance-content p,.data-warning{line-height:1.8;margin:5px 0;overflow-wrap:anywhere}.data-warning{color:var(--warning,#d9b879);font-size:11px}.data-fingerprint{font-size:10px;color:var(--text-muted)}code{word-break:break-all}@media(max-width:600px){.data-provenance time{flex-basis:100%;margin-left:22px}.provenance-content dl{display:grid;gap:12px}.data-provenance summary{gap:6px 10px}}@media(prefers-reduced-motion:reduce){.data-provenance summary,.data-provenance summary:before{transition:none}}
</style>
