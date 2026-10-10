<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { PerformanceBasis } from '../types'
import { formatMarketTime } from '../bar-time'

const props = defineProps<{ basis: PerformanceBasis }>()
const position = ref(0)
const entries = computed(() => [
  ...(props.basis.valuation_samples || []).map(sample => ({ ...sample, closed_period: !!sample.closed_period, carryFrom: null as string | null, excluded: false, reason: '', excludedMembers: [] as string[] })),
  ...(props.basis.excluded_targets || []).map(target => ({ datetime: target.datetime, valid: false, members: [], closed_period: false, carryFrom: null as string | null, excluded: true, reason: target.reason, excludedMembers: target.members })),
  ...(props.basis.closed_period_samples || []).filter(sample => !props.basis.valuation_samples?.some(item => item.datetime === sample.datetime)).map(sample => ({ datetime: sample.datetime, valid: Number.isFinite(sample.valuation) && (sample.valuation ?? 0) > 0, members: [], closed_period: true, carryFrom: sample.source_time || null, excluded: false, reason: sample.reason, excludedMembers: [] as string[] })),
].sort((a, b) => b.datetime.localeCompare(a.datetime)))
const current = computed(() => entries.value[position.value])
watch(() => props.basis, () => { position.value = 0 })
const labels: Record<string, string> = { DAY: '日线', WEEK: '周线', MONTH: '月线', SEASON: '季线', YEAR: '年线', INTRADAY: '日内' }
function categoryLabel(value: string) { return labels[value] || value.replace('MIN_', '') + ' 分钟' }
</script>

<template>
  <details v-if="entries.length" class="valuation-details">
    <summary>估值采样依据 <span v-if="basis.valuation_samples">{{ basis.valuation_samples.length }} 个采样时点 · {{ basis.excluded_targets?.length || 0 }} 个范围外时点</span><span v-else>{{ basis.closed_period_samples?.length || 0 }} 个休市周期沿用估值</span></summary>
    <div v-if="current" class="valuation-body">
      <div class="valuation-nav">
        <strong>{{ formatMarketTime(current.datetime) }}</strong>
        <span class="valuation-state">{{ current.excluded ? '范围外，不参与年化' : !current.valid ? '采样缺失，不计算年化' : current.closed_period ? '整周期休市 · 估值沿用' : '采样有效' }}</span>
        <nav aria-label="估值采样时点">
          <button type="button" :disabled="position === 0" aria-label="较新的估值时点" @click="position--">较新</button>
          <span aria-live="polite">{{ position + 1 }} / {{ entries.length }}</span>
          <button type="button" :disabled="position >= entries.length - 1" aria-label="较早的估值时点" @click="position++">较早</button>
        </nav>
      </div>
      <p v-if="current.excluded">{{ current.reason }}：{{ current.excludedMembers.join('、') }}</p>
      <p v-else-if="current.closed_period">{{ current.reason || '交易所整个周期休市；沿用各成员最近应完成周期的估值，未增加行情或交易记录。' }}<template v-if="current.carryFrom"> 沿用观测：{{ formatMarketTime(current.carryFrom) }}。</template></p>
      <div v-for="member in current.members" :key="member.member" class="valuation-member">
        <header><strong>{{ member.member }}</strong><span>{{ categoryLabel(member.category) }}</span></header>
        <dl>
          <dt>应有收盘</dt><dd>{{ formatMarketTime(member.expected_time) }}</dd>
          <dt>实际估值</dt><dd>{{ member.valuation_time ? formatMarketTime(member.valuation_time) : '没有可用估值' }}</dd>
          <dt>原始标签</dt><dd>{{ member.source_time ? formatMarketTime(member.source_time) : '—' }}</dd>
        </dl>
        <p v-if="member.reason" role="status">{{ member.reason }}</p>
        <p v-else-if="member.asof_age_seconds">沿用此前已完成周期的估值，并非当前时点的实时价格。</p>
      </div>
    </div>
  </details>
</template>

<style scoped>
.valuation-details{margin:12px 0;font-size:11px;line-height:1.7;color:var(--text-muted);min-width:0}
summary{cursor:pointer;padding:6px 0;color:var(--text);overflow-wrap:anywhere}summary span{color:var(--text-muted);margin-left:10px}
.valuation-body{padding:6px 0 0 14px}.valuation-nav{display:flex;align-items:center;gap:6px 14px;flex-wrap:wrap}
strong{font-weight:500;color:var(--text)}.valuation-state{font-size:11px}nav{display:flex;align-items:center;gap:10px;margin-left:auto;font-variant-numeric:tabular-nums}
button{font:inherit;color:var(--text);background:none;border:1px solid var(--border);border-radius:6px;min-height:30px;padding:2px 9px;cursor:pointer;transition:background .12s}button:hover:not(:disabled){background:var(--bg-elevated)}button:disabled{opacity:.4;cursor:default}button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.valuation-member{border-top:1px solid var(--border);margin-top:12px;padding-top:10px}header{display:flex;flex-wrap:wrap;gap:4px 12px;overflow-wrap:anywhere}dl{display:grid;grid-template-columns:70px minmax(0,1fr);gap:3px 10px;margin:8px 0;font-variant-numeric:tabular-nums}dt,dd{margin:0}dd{color:var(--text);overflow-wrap:anywhere}p{margin:6px 0;overflow-wrap:anywhere}
@media(max-width:600px){.valuation-body{padding-left:8px}summary span{display:block;margin-left:14px}nav{width:100%;justify-content:space-between;margin-top:4px}button{min-height:36px}}
@media(prefers-reduced-motion:reduce){button{transition:none}}
</style>
