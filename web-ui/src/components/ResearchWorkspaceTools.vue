<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useAuth } from '../auth'
import { useResearchPreferences, normalizeResearchPreferences } from '../research-preferences'
import { validateResearchSnapshot } from '../research-snapshot-validation'
import { listResearchSnapshots, readResearchSnapshot, saveResearchSnapshot, deleteResearchSnapshot, snapshotSummary, type ResearchSnapshot, type SnapshotSummary } from '../research-snapshots'
import { periodLabel } from '../period-comparison'
import ChanlunChart from './ChanlunChart.vue'
import ChartFrame from './ChartFrame.vue'
import PeriodStructureInspector from './PeriodStructureInspector.vue'
import CloudResearchArchives from './CloudResearchArchives.vue'
import type { ArchiveDraft } from '../cloud-archives'
import ArchivedRadarSource from './ArchivedRadarSource.vue'

const props = defineProps<{ capture: () => Omit<ResearchSnapshot, 'schema' | 'id' | 'owner' | 'name' | 'note' | 'savedAt'>; busy: boolean }>()
const { currentUser } = useAuth()
const preferences = useResearchPreferences()
const mobileSheet = computed({ get: () => preferences.settings.value.mobileSheet, set: value => preferences.patch({ mobileSheet: value }) })
const list = shallowRef<SnapshotSummary[]>([]), viewing = shallowRef<ResearchSnapshot | null>(null)
const name = ref(''), note = ref(''), message = ref(''), saving = ref(false), deleting = ref(''), resetPending = ref(false)
const dialog = ref<HTMLDialogElement>(), returnFocus = ref<HTMLElement | null>(null)
const importInput = ref<HTMLInputElement>()
function captureCloud(): ArchiveDraft {
  const data=props.capture()
  const title=(name.value.trim() || `${data.title} · ${data.cutoff}`).slice(0,120)
  return {kind:'chart',name:title,note:note.value,payload:{...data,schema:1,name:title,note:note.value,savedAt:new Date().toISOString()}}
}
const snapshotCharts = new Map<string, InstanceType<typeof ChanlunChart>>()
const snapshotInspectors = new Map<string, InstanceType<typeof PeriodStructureInspector>>()
let generation = 0
watch(() => currentUser.value?.id, async owner => {
  const version = ++generation
  close(); list.value = []; message.value = ''; name.value = ''; note.value = ''; deleting.value = ''
  if (!owner) return
  try { const records = await listResearchSnapshots(owner); if (version === generation) list.value = records }
  catch (error) { if (version === generation) message.value = String(error) }
}, { immediate: true })
async function save() {
  const owner = currentUser.value?.id
  if (!owner || saving.value || props.busy) return
  saving.value = true; message.value = ''
  try {
    const payload = props.capture()
    const snapshot: ResearchSnapshot = JSON.parse(JSON.stringify({ ...payload, schema: 1, id: crypto.randomUUID(), owner,
      name: name.value.trim() || `${payload.title} · ${payload.cutoff}`, note: note.value, savedAt: new Date().toISOString() }))
    await saveResearchSnapshot(snapshot)
    if (owner === currentUser.value?.id) { list.value = [snapshotSummary(snapshot), ...list.value]; message.value = '已保存到当前浏览器。建议导出备份，清除浏览器数据会丢失本地快照。' }
  } catch (error) { message.value = String(error) }
  finally { saving.value = false }
}
async function open(summary: SnapshotSummary) {
  const owner = currentUser.value?.id
  if (!owner) return
  returnFocus.value = document.activeElement as HTMLElement
  try {
    const snapshot = await readResearchSnapshot(summary.id, owner)
    if (owner !== currentUser.value?.id) return
    viewing.value = validateResearchSnapshot(snapshot); await nextTick(); dialog.value?.showModal()
  } catch (error) { message.value = String(error) }
}
function close() { dialog.value?.close(); viewing.value = null; snapshotCharts.clear(); snapshotInspectors.clear(); returnFocus.value?.focus({ preventScroll: true }) }
async function importBackup(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0], owner = currentUser.value?.id
  if (!file || !owner) return
  saving.value = true
  try {
    if (file.size > 25 * 1024 * 1024) throw new Error('导入文件不能超过 25MB')
    const data = validateResearchSnapshot(JSON.parse(await file.text()))
    if (owner !== currentUser.value?.id) return
    const snapshot: ResearchSnapshot = { ...data, id: crypto.randomUUID(), owner, savedAt: new Date().toISOString(),
      name: `${data.name}（导入）`, preferences: normalizeResearchPreferences(data.preferences) }
    await saveResearchSnapshot(snapshot)
    if (owner === currentUser.value?.id) { list.value = [snapshotSummary(snapshot), ...list.value]; message.value = '已导入备份。内容由文件提供，未经过服务器重新核验。' }
  } catch (error) { message.value = `导入失败：${String(error)}` }
  finally { saving.value = false; input.value = '' }
}
async function remove(snapshot: SnapshotSummary) {
  if (deleting.value !== snapshot.id) { deleting.value = snapshot.id; return }
  try {
    await deleteResearchSnapshot(snapshot.id, currentUser.value?.id ?? '')
    list.value = list.value.filter(item => item.id !== snapshot.id); deleting.value = ''
    message.value = '已删除此浏览器中的快照；如已导出，可保留导出文件查阅。'
  } catch (error) { message.value = String(error) }
}
async function download(summary: SnapshotSummary) {
  const owner = currentUser.value?.id
  if (!owner) return
  try {
  const snapshot = await readResearchSnapshot(summary.id, owner)
  if (owner !== currentUser.value?.id) return
  // Do not put internal account IDs in the exported document.
  const blob = new Blob([JSON.stringify({ ...snapshot, owner: undefined }, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob), a = document.createElement('a')
  a.href = url; a.download = `tdx-research-${snapshot.savedAt.slice(0, 10)}-${snapshot.id.slice(0, 8)}.json`; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) { message.value = String(error) }
}
onBeforeUnmount(() => { generation++; dialog.value?.close() })
</script>
<template>
  <details class="workspace-tools research-panel research-hierarchy">
    <summary><strong>研究偏好与快照</strong><span>账户偏好 · 本地快照</span></summary>
    <div class="workspace-body">
      <div class="workspace-row"><label><input v-model="mobileSheet" type="checkbox" />手机使用底部详情面板</label><div class="workspace-actions"><button v-if="!resetPending" @click="resetPending = true">恢复默认图表设置</button><template v-else><button @click="preferences.reset(); resetPending = false">确认恢复</button><button @click="resetPending = false">取消</button></template></div></div>
      <p>均线、指标、线宽、透明度、对照周期和布局按账户保存。恢复默认不会改变行情、分析规则或删除快照。</p>
      <p v-if="preferences.saveStatus.value" role="status">{{ preferences.saveStatus.value }} <button v-if="preferences.saveStatus.value.includes('失败')" @click="preferences.retry">重试保存</button></p>
      <div class="snapshot-form"><label>快照名称<input v-model="name" maxlength="120" placeholder="留空则使用标的与截止时间" /></label><label>研究备注<textarea v-model="note" maxlength="4000" rows="2" placeholder="记录观察与待核验问题" /></label><button :disabled="busy || saving || !currentUser" @click="save">{{ saving ? '保存中…' : '保存当前研究快照' }}</button></div>
      <p>快照包含当前可见行情、分析原始结果、复权与采集口径、返回的规则版本、图表设置及备注。保存在此浏览器，按登录账户隔离显示；不跨设备同步，也不是加密保险箱。</p>
      <input ref="importInput" type="file" accept="application/json,.json" hidden @change="importBackup" /><button :disabled="saving || !currentUser" @click="importInput?.click()">导入快照备份</button>
      <p role="status">{{ message }}</p>
      <ul class="snapshot-list"><li v-for="snapshot in list" :key="snapshot.id"><div><strong>{{ snapshot.name }}</strong><span>{{ snapshot.savedAt.replace('T', ' ').slice(0, 19) }} UTC · {{ snapshot.charts.map(chart => periodLabel(chart.category)).join(' / ') }}</span></div><div class="workspace-actions"><button @click="open(snapshot)">查看</button><button @click="download(snapshot)">导出</button><button @click="remove(snapshot)">{{ deleting === snapshot.id ? '确认删除' : '删除' }}</button><button v-if="deleting === snapshot.id" @click="deleting = ''">取消</button></div></li></ul>
      <p v-if="!list.length">尚无本地研究快照。</p>
    </div>
  </details>
  <CloudResearchArchives :capture="captureCloud" :busy="busy || saving" />
  <Teleport to="body"><dialog ref="dialog" class="snapshot-dialog" aria-label="已保存研究快照" @cancel.prevent="close">
    <template v-if="viewing"><header><div><strong>{{ viewing.name }}</strong><p>保存的分析结果 · 不重新计算 · 不修改当前研究</p></div><button @click="close">关闭快照</button></header>
      <div class="snapshot-scroll"><p>{{ viewing.note }}</p><p>共同截止 {{ viewing.cutoff }} · 界面版本 {{ viewing.frontendVersion }} · 规则版本 {{ viewing.ruleVersions.join('、') || '接口未返回统一版本，详见原始结果' }}</p><p>这是保存时的数据版本，不代表历史时点实际可知的数据版本。确认与失效时间保留原记录。</p>
        <ArchivedRadarSource :source="viewing.radarSource" :legacy-reference="viewing.charts.some(chart=>!!chart.metadata.original_task)" />
        <section v-for="chart in viewing.charts" :key="chart.category"><ChartFrame :title="`${viewing.title} · ${periodLabel(chart.category)}`" :description="`采集 ${chart.metadata.observed_at} · 实际复权 ${chart.metadata.actual_adjust} · ${chart.bars.length} 根`">
          <ChanlunChart :ref="el => el && snapshotCharts.set(chart.category, el as InstanceType<typeof ChanlunChart>)" :bars="chart.bars" :result="chart.result" :layers="viewing.layers" :show-divergence-history="viewing.history" :frozen-indicators="chart.frozenIndicators" readonly-archive :ma-periods="viewing.preferences.ma.filter(item => item.enabled).map(item => item.period)" :ma-available-periods="viewing.preferences.ma.map(item => item.period)" :line-widths="viewing.preferences.widths" :candle-transparency="viewing.preferences.transparency" :indicator-config="viewing.preferences.indicators" @inspect="snapshotInspectors.get(chart.category)?.inspect($event)" />
        </ChartFrame><PeriodStructureInspector :ref="el => el && snapshotInspectors.set(chart.category, el as InstanceType<typeof PeriodStructureInspector>)" :result="chart.result" :bars="chart.bars" :title="periodLabel(chart.category)" @locate="snapshotCharts.get(chart.category)?.locate($event)" /></section>
      </div>
    </template>
  </dialog></Teleport>
</template>
<style scoped>
.workspace-tools { margin-top: 18px; }
.workspace-body { padding: 14px 0 10px 20px; }
.workspace-row, .workspace-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.workspace-row { justify-content: space-between; }
label { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted); }
input[type=checkbox] { width: 14px; height: 14px; min-height: 14px; padding: 0; margin: 0; flex: 0 0 14px; accent-color: #85b5e8; }
button { min-height: 32px; padding: 5px 10px; color: var(--text-muted); background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 7px; font-size: 11px; cursor: pointer; }
button:disabled { opacity: .45; cursor: default; }
button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
p { color: var(--text-muted); font-size: 11px; line-height: 1.9; overflow-wrap: anywhere; }
.snapshot-form { display: grid; gap: 10px; margin-top: 18px; max-width: 660px; }
.snapshot-form label { display: grid; grid-template-columns: 80px minmax(0,1fr); }
.snapshot-form input, textarea { min-width: 0; padding: 8px; border: 1px solid var(--border); border-radius: 6px; color: var(--text); background: var(--bg-deep); font: inherit; }
textarea { resize: vertical; }.snapshot-form > button { justify-self: end; }
.snapshot-list { padding: 0; list-style: none; }
.snapshot-list li { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; border-top: 1px solid var(--border); padding: 12px 0; }
.snapshot-list strong { font-size: 12px; overflow-wrap: anywhere; }.snapshot-list span { display: block; margin-top: 4px; color: var(--text-muted); font-size: 10px; }
.snapshot-dialog { width: min(1440px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); box-sizing: border-box; border: 1px solid var(--border); border-radius: 14px; padding: 0; background: var(--bg); color: var(--text); }
.snapshot-dialog::backdrop { background: #0009; }.snapshot-dialog > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 20px; border-bottom: 1px solid var(--border); }.snapshot-dialog header p { margin: 4px 0 0; }
.snapshot-scroll { padding: 16px 20px; overflow: auto; max-height: calc(100dvh - 150px); }.snapshot-scroll section + section { margin-top: 24px; }
@media(max-width:600px) { .workspace-body { padding-left: 8px; } .snapshot-form label { grid-template-columns: 1fr; } .snapshot-dialog { width: calc(100vw - 12px); } .snapshot-scroll, .snapshot-dialog > header { padding: 12px; } }
</style>
