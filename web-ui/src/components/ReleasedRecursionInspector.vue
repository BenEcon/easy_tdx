<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ReleasedRecursion } from '../types'
import { releaseEvidence, releaseReason } from '../released-evidence'
import { decompositionRange as range } from '../decomposition-evidence'
import { engineeringValue as value } from '../engineering-trend-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'
import ReleasedMovementExplorer from './ReleasedMovementExplorer.vue'
import type { ReleaseFocusMode } from '../released-focus'

const props = withDefaults(defineProps<{ data?: ReleasedRecursion; total: number; busy: boolean; locatable?: boolean }>(), {locatable: true})
const emit = defineEmits<{ seek: [position: number]; locate: [id: string, mode: ReleaseFocusMode] }>()
const evidence = computed(() => releaseEvidence(props.data, props.total))
const domainRange = (id: string) => range(evidence.value?.domains.get(id)?.source_segment_indices ?? [])
const expanded = ref(new Set<string>())
function toggleExplorer(id: string, event: Event) {
  if ((event.target as HTMLDetailsElement).open) expanded.value.add(id)
  else expanded.value.delete(id)
}
</script>

<template>
  <details class="released-inspector research-panel">
    <summary><strong>全域走势递归</strong><span v-if="evidence">外部 {{ data!.external_frontier_ids.length }} 条 · 最高 M{{ data!.highest_external_level }} · 已确认口径</span><span v-else>等待可核验快照</span></summary>
    <div class="research-panel-body">
    <dl class="research-copy">
      <div><dt>对外准入</dt><dd>父走势<strong>独立完成并完整覆盖相关归属区</strong>后，才允许对外组合。</dd></div>
      <div><dt>来源与层级</dt><dd>内部子走势保留为依据，不重复占用。层级不对应日线或周线。</dd></div>
      <div v-if="evidence"><dt>核验截止</dt><dd>{{ data!.as_of_date ?? (data!.as_of_index === null ? '暂无数据' : `#${data!.as_of_index}`) }}</dd></div>
    </dl>
    <p v-if="!evidence" class="research-empty">{{ data ? '本快照的来源或确认依赖无法核验，请重新分析。' : '此旧快照未包含全域递归结果，请重新分析。' }}</p>
    <template v-else>
      <p class="research-caveat"><strong>使用边界</strong><span>采用已确认的结构、MACD 和反向确认规则；未接入交易信号，不声称原著唯一分解。</span></p>
      <details class="coverage reading-disclosure">
        <summary><strong>全来源覆盖</strong><span class="coverage-count"><b>{{ data!.accepted_segment_count }}</b> 条基础线段</span></summary>
        <p class="coverage-intro">按基础线段顺序，查看每组来源的结构层级与当前归属。</p>
        <div v-if="evidence.cover.length" class="coverage-table" role="table" aria-label="基础线段来源覆盖">
          <div role="rowgroup"><div class="cover-heading" role="row"><span role="columnheader">基础来源</span><span role="columnheader">结构层级</span><span role="columnheader">当前状态</span></div></div>
          <div role="rowgroup">
            <div v-for="(block, i) in evidence.cover" :key="i" class="cover-row" role="row">
              <div class="cover-source" role="rowheader"><span class="cover-ordinal" aria-hidden="true">{{ String(i + 1).padStart(2, '0') }}</span><div><strong>{{ range(block.source_segment_indices) }}</strong><small>{{ block.source_segment_indices.length }} 条基础线段</small></div></div>
              <div class="cover-level" role="cell"><span class="cover-mobile-label" aria-hidden="true">层级</span><strong>{{ block.level ? `M${block.level}` : '基础来源' }}</strong></div>
              <div class="cover-placement" role="cell"><span class="research-status" :class="{ available: block.status === 'external_completed', internal: block.status === 'internal_completed', unresolved: block.status === 'unresolved' }">{{ block.status === 'external_completed' ? '外部可用' : block.status === 'internal_completed' ? '区内保留' : '待解决' }}</span><small>{{ block.status === 'external_completed' ? '可参与对外组合' : block.status === 'internal_completed' ? '保留内部结构依据' : '尚未归入完成结构' }}</small></div>
            </div>
          </div>
        </div>
        <p v-if="!evidence.cover.length" class="research-empty">当前没有可接纳的已确认线段。</p>
        <p v-else class="coverage-footnote">来源完整保留；基础连接段不等同于高层完成走势。</p>
      </details>
      <p v-if="!evidence.frontier.length" class="research-empty">尚无通过当前归属核验的完成结构；原始来源仍完整保留。</p>
      <details v-for="record in evidence.frontier" :key="record.id" class="movement">
        <summary class="research-record-heading"><strong>M{{ record.level }} · {{ record.direction === 'up' ? '向上' : '向下' }}{{ record.kind === 'consolidation' ? '盘整' : '趋势' }}</strong><span>{{ range(record.source_segment_indices) }}</span><small class="research-status" :class="{ available: record.eligible_for_external_recursion }">{{ record.eligible_for_external_recursion ? '外部可用' : '区内保留' }}</small></summary>
        <dl class="research-facts">
          <dt>价格起止</dt><dd>{{ value(record.start_value) }} → {{ value(record.end_value) }}</dd>
          <dt>局部可知</dt><dd>{{ record.original_known_date ?? `#${record.original_known_index}` }}</dd>
          <dt>结构可用</dt><dd>{{ record.known_date ?? `#${record.known_index}` }}</dd>
          <dt>当前准入</dt><dd>{{ record.current_placement.known_date ?? `#${record.current_placement.known_index}` }} · 不改写原完成时点</dd>
          <dt>整区覆盖</dt><dd>{{ record.current_placement.released_domain_ids.length ? record.current_placement.released_domain_ids.map(domainRange).join('；') : '本结构没有释放其他归属区' }}</dd>
          <dt>仍受约束</dt><dd>{{ record.current_placement.enclosing_domain_ids.length ? record.current_placement.enclosing_domain_ids.map(domainRange).join('；') : '无区内约束' }}</dd>
          <dt>MACD 依据</dt><dd>C/A 柱面积 {{ value(record.macd_evidence.area_ratio) }}；DIF {{ value(record.macd_evidence.a_dif_extreme) }} → {{ value(record.macd_evidence.c_dif_extreme) }}；DEA {{ value(record.macd_evidence.a_dea_extreme) }} → {{ value(record.macd_evidence.c_dea_extreme) }}</dd>
          <dt>反向确认</dt><dd>{{ record.level === 1 ? '相邻反向基础线段' : `独立 M${record.level - 1} 结构` }}，只作确认依据，不加入本走势价格来源</dd>
        </dl>
        <ConfirmationReplay :index="record.current_placement.known_index" :total="total" :busy="busy" :label="`M${record.level} 准入核验`" @seek="emit('seek', $event)" />
        <details class="reading-disclosure" @toggle="toggleExplorer(record.id, $event)"><summary>逐层查看子走势与反向确认</summary>
          <ReleasedMovementExplorer v-if="expanded.has(record.id)" :data="data!" :root-id="record.id" :total="total" :busy="busy" :locatable="locatable" @seek="emit('seek', $event)" @locate="(id, mode) => emit('locate', id, mode)" />
        </details>
      </details>
      <details v-if="evidence.deferred.length" class="deferred reading-disclosure">
        <summary>待解决的父级与局部依据 · {{ evidence.deferred.length }} 项</summary>
        <p class="research-reading">局部完成不代表可对外使用；不通过的父级不会遮挡已经合法的下级结构。</p>
        <div class="deferred-list">
          <section v-for="record in evidence.deferred" :key="record.id" class="deferred-row">
            <strong>M{{ record.level }} · {{ range(record.source_segment_indices) }}</strong>
            <p>{{ releaseReason(record.current_placement.reason) }}</p>
            <p v-if="record.required_domain_ids.length">仍需解决：{{ record.required_domain_ids.map(domainRange).join('；') }}</p>
            <ConfirmationReplay :index="record.original_known_index" :total="total" :busy="busy" label="局部完成" @seek="emit('seek', $event)" />
            <details class="reading-disclosure" @toggle="toggleExplorer(record.id, $event)"><summary>逐层查看仍受约束的依据</summary>
              <ReleasedMovementExplorer v-if="expanded.has(record.id)" :data="data!" :root-id="record.id" :total="total" :busy="busy" :locatable="locatable" @seek="emit('seek', $event)" @locate="(id, mode) => emit('locate', id, mode)" />
            </details>
          </section>
        </div>
      </details>
    </template>
    </div>
  </details>
</template>

<style scoped>
.released-inspector { grid-column: 1 / -1; min-width: 0; border-top: 1px solid var(--border); padding-top: 14px; font-size: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.8; overflow-wrap: anywhere; }
summary strong { margin-right: 12px; color: var(--text); font-weight: 550; }
summary span, p, dt, small, .cover-row { color: var(--text-muted); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
p { line-height: 1.8; margin: 6px 0 12px; overflow-wrap: anywhere; }
.movement, .coverage, .deferred, .deferred-row { border-top: 1px solid var(--border); }
small { margin-left: 12px; font-size: 11px; }
dl { display: grid; grid-template-columns: 84px minmax(0, 1fr); gap: 7px 12px; margin: 8px 0; line-height: 1.8; }
dd { margin: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.cover-row { display: grid; grid-template-columns: minmax(0, 1fr) 64px 72px; gap: 8px; padding: 8px 0; line-height: 1.6; border-top: 1px solid var(--border); }
.deferred-row { padding: 10px 0; }
.deferred-row strong { font-weight: 550; }
.deferred-list { max-height: 420px; overflow: auto; }
@media (max-width: 560px) { dl { grid-template-columns: 70px minmax(0, 1fr); gap: 6px 8px; } summary span { display: block; } small { margin-left: 0; } }
</style>
