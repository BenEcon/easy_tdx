<script setup lang="ts">
import { computed } from 'vue'
import type { EngineeringTrendHierarchy, EngineeringMovementHierarchy } from '../types'
import ConfirmationReplay from './ConfirmationReplay.vue'
import RecursiveCentreInspector from './RecursiveCentreInspector.vue'
import { engineeringSource as source, engineeringValue as value } from '../engineering-trend-evidence'
import { decompositionRange } from '../decomposition-evidence'

const props = defineProps<{ data?: EngineeringTrendHierarchy | EngineeringMovementHierarchy; total: number; busy: boolean; historical?: boolean }>()
const mixed = computed(() => props.data?.scope === 'engineering_mixed_movements')
const prefix = computed(() => mixed.value ? 'M' : 'T')
const highest = computed(() => props.data?.scope === 'engineering_mixed_movements'
  ? props.data.highest_completed_movement_level : props.data?.highest_completed_trend_level)
const emit = defineEmits<{ seek: [position: number] }>()
</script>

<template>
  <details class="trend-inspector research-panel">
    <summary><strong>{{ mixed ? '工程走势递归' : '工程趋势递归' }}<span v-if="historical" class="research-version">旧解释</span></strong><span>{{ highest ? `最高 ${prefix}${highest} · 工程确认` : '等待完整走势证据' }}</span></summary>
    <div class="research-panel-body">
    <p v-if="historical" class="research-caveat research-history"><strong>历史对照</strong><span>保留原规则和原确认时间用于对照；当前内外归属与可用输入以“分层归属与内部递归”为准。</span></p>
    <dl class="research-copy">
      <div><dt>完成条件</dt><dd v-if="mixed">单中枢盘整与同向分离中枢趋势，均需 A/C 创新极值、MACD 面积与双线背驰，再等<strong>反向次级结构确认</strong>。</dd><dd v-else>同级中枢分离、A/C 区间 MACD 面积与双线背驰，并等<strong>反向次级结构确认</strong>。</dd></div>
      <div><dt>递归层级</dt><dd v-if="mixed">M1 从线段构成，M2 从连续的 M1 构成；不代表日线、周线。</dd><dd v-else>T1 从线段构成，T2 从连续的 T1 构成；不代表日线、周线。</dd></div>
    </dl>
    <p v-if="!data" class="research-empty">此快照尚未包含工程趋势，请重新分析。</p>
    <p v-else-if="!data.levels.length" class="research-empty">尚无同时满足以上条件的走势；未确认尾部、结构冲突和来源空档不会被强行拼接。</p>
    <section v-for="level in data?.levels" :key="level.level" :aria-label="`${prefix}${level.level} 工程走势`">
      <h4>{{ prefix }}{{ level.level }} <span>{{ level.types.length }} 条走势 · {{ level.input_chain_count }} 条连续输入链 · {{ level.unresolved_input_ids.length }} 个输入待判定</span></h4>
      <details v-for="trend in level.types" :key="trend.id" class="trend-row">
        <summary>
          <strong>{{ trend.kind === 'consolidation' ? (trend.direction === 'up' ? '向上盘整' : '向下盘整') : (trend.direction === 'up' ? '上涨趋势' : '下跌趋势') }}</strong>
          <span>{{ trend.start_date ?? `#${trend.start_index}` }} → {{ trend.end_date ?? `#${trend.end_index}` }}</span>
          <span class="price">{{ value(trend.start_value) }} → {{ value(trend.end_value) }}</span>
        </summary>
        <dl class="research-facts">
          <dt>实际确认</dt><dd>{{ trend.known_date ?? `#${trend.known_index}` }}；极值日期不等于可知日期</dd>
          <dt>完成依据</dt><dd>{{ trend.kind === 'consolidation' ? '单中枢盘整背驰' : `${trend.centres.length} 个同向分离中枢` }}；C/A 柱面积 {{ value(trend.macd_evidence.area_ratio) }}</dd>
          <dt>DIF / DEA</dt><dd>A：{{ value(trend.macd_evidence.a_dif_extreme) }} / {{ value(trend.macd_evidence.a_dea_extreme) }}；C：{{ value(trend.macd_evidence.c_dif_extreme) }} / {{ value(trend.macd_evidence.c_dea_extreme) }}</dd>
          <dt>反向确认来源</dt><dd>{{ source(trend.opposite_id) }}（不占用本走势来源）</dd>
          <dt>原始来源</dt><dd>{{ decompositionRange(trend.source_segment_indices) }}，共 {{ trend.source_segment_indices.length }} 段</dd>
        </dl>
        <details class="children"><summary>查看 {{ trend.child_ids.length }} 个次级来源</summary><p>{{ trend.child_ids.map(source).join(' · ') }}</p></details>
        <ConfirmationReplay :index="trend.known_index" :total="total" :busy="busy" :label="`${prefix}${level.level} ${trend.kind === 'consolidation' ? '盘整' : '趋势'}`" @seek="emit('seek', $event)" />
      </details>
    </section>
    <RecursiveCentreInspector :layers="data?.structure_layers" :prefix="prefix" :total="total" :busy="busy" @seek="emit('seek', $event)" />
    <p v-if="data?.rejected_suffix_count">{{ data.rejected_suffix_count }} 条未确认或无效后缀未参与计算。</p>
    <p class="boundary research-caveat"><strong>使用边界</strong><span>{{ mixed ? '按已约定规则递归组合盘整与趋势；不等于完整自然分解，扩展重组完成仍待实现。' : '仅趋势分支，盘整结束、扩展重组与混合类型的完整自然递归仍未完成。' }}MACD 沿用原图序列并按本层 A/C 区间比较；不新增交易信号。</span></p>
    </div>
  </details>
</template>

<style scoped>
.trend-inspector { grid-column: 1 / -1; min-width: 0; border-top: 1px solid var(--border); padding-top: 14px; font-size: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.8; overflow-wrap: anywhere; }
summary strong { margin-right: 12px; color: var(--text); font-weight: 550; }
summary span, p, dt, h4 span { color: var(--text-muted); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
p { line-height: 1.8; margin: 6px 0 12px; overflow-wrap: anywhere; }
h4 { margin: 16px 0 4px; color: var(--text); font-size: 12px; font-weight: 550; }
h4 span { margin-left: 10px; font-size: 11px; font-weight: 400; }
.trend-row { border-top: 1px solid var(--border); }
.price { margin-left: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
dl { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 7px 12px; margin: 8px 0; line-height: 1.8; }
dd { margin: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.children summary { color: var(--text-dim); font-size: 11px; padding: 5px 0; }
.boundary { border-top: 1px solid var(--border); margin-top: 12px; padding-top: 10px; }
@media (max-width: 600px) { .trend-row > summary span { display: block; margin-left: 16px; } h4 span { display: block; margin-left: 0; } dl { grid-template-columns: 78px minmax(0, 1fr); gap: 7px; } }
</style>
