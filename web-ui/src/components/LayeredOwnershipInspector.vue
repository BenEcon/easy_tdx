<script setup lang="ts">
import { computed } from 'vue'
import type { LayeredMovementOwnership } from '../types'
import { currentOwners, internalSource, internalStatus, lifecycleLabel, ownerLabel, ownershipHistory, ownershipLifecycle } from '../ownership-evidence'
import { decompositionRange as range } from '../decomposition-evidence'
import { engineeringValue as value } from '../engineering-trend-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'
import { blockedOwnershipConflict, blockedOwnershipEvidence } from '../blocked-ownership-evidence'

const props = defineProps<{ data?: LayeredMovementOwnership; total: number; busy: boolean; historical?: boolean }>()
const owners = computed(() => currentOwners(props.data))
const history = computed(() => ownershipHistory(props.data))
const blocked = computed(() => new Map(owners.value.map(owner => [owner.id,
  (owner.blocked_ownership_candidates ?? []).map(candidate => ({ candidate,
    evidence: blockedOwnershipEvidence(owner, candidate, props.total),
    conflict: blockedOwnershipConflict(owner, candidate, props.total) }))] as const)))
const lifecycle = computed(() => new Map(owners.value.flatMap(owner =>
  (owner.nested_owners ?? []).map(domain => [domain.id, ownershipLifecycle(domain, props.total, owner)] as const))))
const emit = defineEmits<{ seek: [position: number] }>()
</script>

<template>
  <details class="ownership-inspector research-panel">
    <summary><strong>分层归属与内部递归<span v-if="historical" class="research-version">旧解释</span></strong><span>{{ owners.length }} 个归属区 · 独立解释</span></summary>
    <div class="research-panel-body">
    <dl class="research-copy"><div><dt>内部保留</dt><dd>升级或扩展范围内的完成结构保留在内部。</dd></div><div><dt>父级替代</dt><dd>父级须独立满足完成条件，并在当前输入中替代子级；同一来源不再作为外部独立输入。</dd></div><div v-if="data?.rule === 'layered_recursive_ownership_v2'"><dt>逐层归属</dt><dd>已启用逐层归属：内部再次升级或扩展时继续在对应归属区内核验，不跨区拼接。</dd></div></dl>
    <p v-if="!data" class="research-empty">此快照尚无分层归属结果，请重新分析。</p>
    <p v-else-if="!owners.length" class="research-empty">当前没有升级或扩展归属冲突，沿用外部工程输入。</p>
    <section v-for="owner in owners" :key="owner.id" class="owner">
      <h4>{{ range(owner.source_segment_indices) }} <span>归属区 · 非已完成走势</span></h4>
      <p>{{ owner.claims.some(c => c.kind === 'promotion') ? '含升级证明' : '扩展归属' }} · 更新于 {{ owner.known_date ?? `#${owner.known_index}` }} · {{ owner.unresolved_segment_indices.length }} 段尚未被内部完成结构覆盖</p>
      <p v-if="!owner.levels.length">归属已明确，内部走势尚未满足完成条件。</p>
      <details v-if="owner.nested_owners?.length" class="children">
        <summary>高层归属 · {{ owner.nested_owners.length }} 个内部范围</summary>
        <section v-for="domain in owner.nested_owners" :key="domain.id" class="history-row">
          <h5>{{ ownerLabel(owner, domain.id) }}</h5>
          <p>{{ domain.claim_kinds.includes('promotion') ? '含升级证明' : '扩展归属' }} · 上属：{{ ownerLabel(owner, domain.parent_owner_id) }} · {{ domain.source_unit_ids.length }} 个次级输入 · 归属形成于 {{ domain.known_date ?? `#${domain.known_index}` }}，不是走势完成时间。</p>
          <details class="children"><summary>查看形成、扩展与合并历程</summary>
            <p>按本版父域上下文重建；范围变化不是走势完成，旧历史详情仍以相应时点回放为准。</p>
            <ol v-if="lifecycle.get(domain.id)" class="lifecycle">
              <li v-for="event in lifecycle.get(domain.id)" :key="event.id">
                <div class="event-heading"><strong>{{ lifecycleLabel(event.kind) }}</strong><time>{{ event.known_date ?? `#${event.known_index}` }}</time></div>
                <p>线段 {{ event.first_source_segment_index + 1 }}–{{ event.last_source_segment_index + 1 }} · {{ event.source_unit_count }} 个次级输入；继承 {{ event.previous_owner_ids.length }} 个范围，新增 {{ event.added_unit_ids.length }} 个输入。</p>
                <ConfirmationReplay :index="event.known_index" :total="total" :busy="busy" :label="lifecycleLabel(event.kind)" @seek="emit('seek', $event)" />
              </li>
            </ol>
            <p v-else>此快照没有可核验的完整历程，请重新分析。</p>
          </details>
          <details class="children"><summary>查看逐项接纳时间</summary>
            <p v-for="admission in domain.member_admissions" :key="admission.unit_id">{{ internalSource(admission.unit_id) }} · {{ admission.admitted_date ?? `#${admission.admitted_index}` }}</p>
          </details>
          <ConfirmationReplay :index="domain.known_index" :total="total" :busy="busy" :label="`M${domain.input_level} 层归属`" @seek="emit('seek', $event)" />
        </section>
      </details>
      <details v-if="blocked.get(owner.id)?.length" class="children rejected">
        <summary>未纳入递归的候选 · {{ blocked.get(owner.id)!.length }} 项</summary>
        <p>以下候选仅有局部完成依据，未通过本版归属检查。本版核验时间不是首次被拒绝的时间。</p>
        <div class="rejected-list" :class="{ 'is-long': (blocked.get(owner.id)?.length ?? 0) > 1 }">
          <section v-for="(item, index) in blocked.get(owner.id)" :key="index" class="history-row">
            <template v-if="item.evidence">
              <div class="event-heading"><strong>{{ item.evidence.reason }}</strong><span>{{ range(item.evidence.sources) }}</span></div>
              <dl class="research-facts">
                <dt>输入层级</dt><dd>{{ item.evidence.inputLevel ? `内部 M${item.evidence.inputLevel}` : '基础线段' }}；不代表日线或周线</dd>
                <dt>原局部完成</dt><dd>{{ item.candidate.original_known_date ?? `#${item.evidence.original}` }}；不等于本版准入</dd>
                <dt>本版核验</dt><dd>{{ owner.known_date ?? `#${item.evidence.asOf}` }}；当前未纳入</dd>
              </dl>
              <details class="children"><summary>查看归属冲突依据</summary>
                <template v-if="item.conflict">
                  <dl class="research-facts">
                    <dt>来源涉及归属</dt><dd>{{ item.conflict.source_domains.length ? item.conflict.source_domains.map(s => range(s)).join('；') : '未进入内层归属区' }}</dd>
                    <dt>反向确认来源</dt><dd>{{ internalSource(item.conflict.opposite.unit_id) }}</dd>
                    <dt>确认结构可知</dt><dd>{{ item.conflict.opposite.known_date ?? `#${item.conflict.opposite.known_index}` }}</dd>
                    <dt>确认结构归属</dt><dd>{{ item.conflict.opposite.owner_source_segment_indices ? range(item.conflict.opposite.owner_source_segment_indices) : '未进入内层归属区' }}</dd>
                  </dl>
                  <p>以上为本版范围；反向确认结构只作依据，不计入候选价格来源。</p>
                </template>
                <p v-else>{{ item.candidate.ownership_conflict ? '冲突明细与本版来源不一致，暂不展示，请重新分析。' : '此旧快照没有冲突明细，请重新分析。' }}</p>
              </details>
              <details class="children"><summary>查看候选输入来源 · {{ item.candidate.source_unit_ids.length }} 项</summary>
                <p>{{ item.candidate.source_unit_ids.map(internalSource).join(' · ') }}</p>
              </details>
              <ConfirmationReplay :index="item.evidence.original" :total="total" :busy="busy" label="原局部完成" @seek="emit('seek', $event)" />
              <button class="review-snapshot" :disabled="busy" @click="emit('seek', item.evidence.asOf + 1)">回放本版核验</button>
            </template>
            <p v-else>此候选的来源、原因或时间无法核验，请重新分析。</p>
          </section>
        </div>
      </details>
      <section v-for="level in owner.levels" :key="level.level">
        <h5>内部 M{{ level.level }} <span>{{ level.types.length }} 条工程完成结构</span></h5>
        <details v-for="record in level.types" :key="record.id" class="movement">
          <summary class="research-record-heading">
            <strong>{{ record.direction === 'up' ? '向上' : '向下' }}{{ record.kind === 'consolidation' ? '盘整' : '趋势' }}</strong>
            <span>{{ range(record.source_segment_indices) }}</span>
            <small>{{ internalStatus(owner, record.id) }}</small>
          </summary>
          <dl class="research-facts">
            <dt>价格区间</dt><dd>{{ value(record.start_value) }} → {{ value(record.end_value) }}</dd>
            <template v-if="record.current_owner_id">
              <dt>当前归属</dt><dd>{{ ownerLabel(owner, record.current_owner_id) }}；不作为外部独立输入</dd>
              <dt>当前归属可用</dt><dd>{{ record.current_owner_known_date ?? `#${record.current_owner_known_index}` }}</dd>
            </template>
            <template v-if="record.original_known_index !== undefined">
              <dt>原完成时间</dt><dd>{{ record.original_known_date ?? `#${record.original_known_index}` }}</dd>
              <dt>初始归属生效</dt><dd>{{ record.ownership_known_date ?? `#${record.ownership_known_index}` }}</dd>
            </template>
            <dt>创建时可用</dt><dd>{{ record.known_date ?? `#${record.known_index}` }}；后续迁移不改写此时间</dd>
            <dt>MACD 依据</dt><dd>C/A 柱面积 {{ value(record.macd_evidence.area_ratio) }}；DIF {{ value(record.macd_evidence.a_dif_extreme) }} → {{ value(record.macd_evidence.c_dif_extreme) }}；DEA {{ value(record.macd_evidence.a_dea_extreme) }} → {{ value(record.macd_evidence.c_dea_extreme) }}</dd>
            <dt>反向确认</dt><dd>{{ internalSource(record.opposite_id) }}（仅作确认，不占用本走势来源）</dd>
          </dl>
          <details v-if="record.ownership_transfers?.length" class="children"><summary>查看当前归属接纳</summary>
            <div v-for="(transfer, i) in record.ownership_transfers" :key="i">
              <p>{{ ownerLabel(owner, transfer.from_owner_id) }} → {{ ownerLabel(owner, transfer.to_owner_id) }} · {{ transfer.known_date ?? `#${transfer.known_index}` }}；保留原完成时间</p>
              <ConfirmationReplay :index="transfer.known_index" :total="total" :busy="busy" label="当前归属接纳" @seek="emit('seek', $event)" />
            </div>
          </details>
          <details class="children"><summary>查看次级来源</summary><p>{{ record.child_ids.map(internalSource).join(' · ') }}</p></details>
          <ConfirmationReplay :index="record.known_index" :total="total" :busy="busy" :label="`内部 M${level.level}`" @seek="emit('seek', $event)" />
        </details>
      </section>
    </section>
    <details v-if="history.length" class="history">
      <summary>归属历史 · {{ history.length }} 个历史时点</summary>
      <p v-if="data?.history_format === 'summary_v1'">当前版本保留完整详情；选择历史回放，按本次行情快照重新计算该时点详情。</p>
      <div v-for="version in history.slice().reverse()" :key="version.id" class="history-row">
        <span>{{ range(version.source_segment_indices) }} · {{ version.known_date ?? `#${version.known_index}` }} · {{ version.highest_completed_internal_level ? `内部 M${version.highest_completed_internal_level}` : '等待内部完成' }}</span>
        <ConfirmationReplay :index="version.known_index" :total="total" :busy="busy" label="归属版本" @seek="emit('seek', $event)" />
      </div>
    </details>
    <p v-if="data" class="boundary research-caveat"><strong>使用边界</strong><span>本路径外部独立 M1：{{ data.external_m1_ids.length }} 条。{{ historical ? '此处保留原内部隔离规则；最新跨域准入请查看“全域走势递归”，不要混合两种解释的来源。' : '内部父级完成不等于整个归属区完成，完整自然递归仍待验证。' }}不新增交易信号。</span></p>
    </div>
  </details>
</template>

<style scoped>
.ownership-inspector { grid-column: 1 / -1; min-width: 0; border-top: 1px solid var(--border); padding-top: 14px; font-size: 12px; }
summary { cursor: pointer; padding: 9px 0; line-height: 1.8; overflow-wrap: anywhere; }
summary strong { margin-right: 12px; color: var(--text); font-weight: 550; }
summary span, p, dt, h4 span, h5 span, small, .history-row { color: var(--text-muted); }
summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
p { line-height: 1.8; margin: 6px 0 12px; overflow-wrap: anywhere; }
h4, h5 { margin: 16px 0 6px; color: var(--text); font-size: 12px; font-weight: 550; }
h4 span, h5 span { margin-left: 10px; font-size: 11px; font-weight: 400; }
.movement, .owner, .history, .history-row { border-top: 1px solid var(--border); }
small { margin-left: 12px; font-size: 11px; }
dl { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 7px 12px; margin: 8px 0; line-height: 1.8; }
dd { margin: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.children summary { color: var(--text-dim); padding: 5px 0; font-size: 11px; }
.history-row { padding: 8px 0; }
.lifecycle { list-style: none; margin: 8px 0; padding: 0 12px; border-left: 1px solid var(--border); max-height: 300px; overflow: auto; }
.lifecycle li { padding: 10px 0; }
.lifecycle li + li { border-top: 1px solid var(--border); }
.event-heading { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; line-height: 1.8; }
.event-heading strong { font-weight: 550; color: var(--text); }
.event-heading time { color: var(--text-muted); font-variant-numeric: tabular-nums; }
.rejected { margin-top: 12px; border-top: 1px solid var(--border); }
.rejected-list { min-width: 0; }
.rejected-list.is-long { max-height: 400px; overflow: auto; }
.review-snapshot { margin: 6px 0 4px; min-height: 28px; padding: 4px 8px; font-size: 10px; }
.review-snapshot:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.boundary { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }
@media (max-width: 600px) { .movement > summary span, small { display: block; margin-left: 16px; } h4 span, h5 span { display: block; margin-left: 0; } dl { grid-template-columns: 84px minmax(0, 1fr); gap: 7px; } }
</style>
