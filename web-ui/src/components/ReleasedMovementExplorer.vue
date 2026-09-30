<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ReleasedRecursion } from '../types'
import { releaseEvidence } from '../released-evidence'
import { releasedFocus, type ReleaseFocusMode } from '../released-focus'
import { decompositionRange as range } from '../decomposition-evidence'
import ConfirmationReplay from './ConfirmationReplay.vue'
import { releaseBlockers } from '../release-review'

const props = withDefaults(defineProps<{ data: ReleasedRecursion; rootId: string; total: number; busy: boolean; locatable?: boolean }>(), {locatable: true})
const emit = defineEmits<{ seek: [position: number]; locate: [id: string, mode: ReleaseFocusMode] }>()
const path = ref<string[]>([])
watch(() => [props.data, props.rootId], () => { path.value = [props.rootId] }, { immediate: true })
const evidence = computed(() => releaseEvidence(props.data, props.total))
const record = computed(() => evidence.value?.records.get(path.value.at(-1)!))
const children = computed(() => record.value?.child_ids.map(id => ({id, value: evidence.value?.records.get(id)})) ?? [])
const reverse = computed(() => evidence.value?.records.get(record.value?.opposite_id ?? ''))
const blockers = computed(() => record.value ? releaseBlockers(props.data, record.value.id, props.total) : [])
const modes: { mode: ReleaseFocusMode; label: string }[] = [
  {mode: 'movement', label: '定位本走势'}, {mode: 'macd', label: '定位 MACD 比较段'},
  {mode: 'reverse', label: '定位反向确认'},
]
function descend(id: string) {
  if (!props.busy && record.value && [...record.value.child_ids, record.value.opposite_id].includes(id)
    && evidence.value?.records.has(id)) path.value.push(id)
}
</script>

<template>
  <section v-if="record" class="explorer" aria-label="父子结构下钻">
    <nav aria-label="结构路径">
      <button v-for="(id, i) in path" :key="id" :disabled="busy || i === path.length - 1"
        @click="path = path.slice(0, i + 1)">M{{ evidence!.records.get(id)!.level }} · {{ range(evidence!.records.get(id)!.source_segment_indices) }}</button>
    </nav>
    <p>{{ record.start_date ?? `#${record.start_index}` }} → {{ record.end_date ?? `#${record.end_index}` }} · {{ record.eligible_for_external_recursion ? '当前外部可用' : '内部依据／仍受约束' }}</p>
    <div v-if="locatable" class="actions">
      <button v-for="item in modes" :key="item.mode"
        :disabled="busy || !releasedFocus(data, record.id, total, item.mode)"
        @click="emit('locate', record.id, item.mode)">{{ item.label }}</button>
    </div>
    <p>反向确认只作证据，不并入父走势价格来源。{{ locatable ? '定位同步作用于价格和已开启的指标面板，不改变回放日期。' : '研究方案只在本区查看，不覆盖主图。' }}</p>
    <div class="children">
      <div v-for="child in children" :key="child.id" class="child">
        <span v-if="!child.value">基础线段 {{ Number(child.id.split(':')[1]) + 1 }}</span>
        <template v-else>
          <span>M{{ child.value.level }} · {{ range(child.value.source_segment_indices) }} · {{ child.value.direction === 'up' ? '向上' : '向下' }}</span>
          <button :disabled="busy" @click="descend(child.id)">查看子走势</button>
        </template>
      </div>
      <div class="child reverse">
        <span>反向确认：{{ reverse ? `M${reverse.level} · ${range(reverse.source_segment_indices)}` : `基础线段 ${Number(record.opposite_id.split(':')[1]) + 1}` }}</span>
        <button v-if="reverse" :disabled="busy" @click="descend(reverse.id)">查看确认依据</button>
      </div>
    </div>
    <ConfirmationReplay :index="record.original_known_index" :total="total" :busy="busy" label="本结构局部完成" @seek="emit('seek', $event)" />
    <details v-if="blockers.length"><summary>距离对外准入还缺什么 · {{ blockers.length }} 项</summary>
      <div v-for="item in blockers" :key="item.domainId" class="blocker">
        <p>归属范围：{{ range(item.sources) }}；最低父层级 M{{ item.requiredLevel }}，本结构 M{{ item.currentLevel }}。</p>
        <p>{{ item.missingSources.length ? `尚未覆盖基础线段 ${item.missingSources.map(s => s + 1).join('、')}` : '已覆盖该区全部价格来源，仍须核验层级及确认依赖' }}。</p>
        <p>依赖路径：{{ item.path.map(node => `M${node.level}（${range(node.sources)}）`).join(' → ') }}</p>
      </div>
      <p>这些条目已具备局部结构、MACD 和反向确认依据，缺口在归属准入；不能误报为“缺 MACD”。未形成候选的原始来源不据此推断唯一失败原因。</p>
    </details>
  </section>
  <p v-else>结构已随快照变化，请重新选择。</p>
</template>

<style scoped>
.explorer { min-width: 0; margin: 12px 0; padding: 12px; border-left: 2px solid var(--accent); background: rgba(74,158,255,.035); }
nav, .actions { display: flex; flex-wrap: wrap; gap: 6px; }
button { min-height: 28px; font-size: 11px; padding: 4px 9px; line-height: 1.5; white-space: normal; overflow-wrap: anywhere; }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
p { color: var(--text-muted); font-size: 11px; line-height: 1.8; margin: 10px 0; overflow-wrap: anywhere; }
.child { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 8px; border-top: 1px solid var(--border); padding: 8px 0; line-height: 1.7; }
.child span { overflow-wrap: anywhere; }
.reverse { color: var(--text-muted); }
.children { max-height: 360px; overflow: auto; margin-bottom: 10px; }
.blocker { border-top: 1px solid var(--border); }
summary { cursor: pointer; padding: 9px 0; }
</style>
