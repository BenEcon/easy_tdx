<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuth } from '../auth'
import { archiveClient, type ArchiveRecord } from '../cloud-archives'
import { listLocalSnapshotSources, readResearchSnapshot } from '../research-snapshots'
import { prepareLocalMigration, uploadLocalMigration, type LocalMigrationPlan } from '../archive-migration'

const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ busy: [value: boolean]; finished: [] }>()
const { currentUser } = useAuth()
const request = archiveClient(() => currentUser.value?.id)
type Row = { id: string; name: string; selected: boolean; plan?: LocalMigrationPlan; state: 'ready'|'invalid'|'uploading'|'saved'|'deleted'|'failed'; message: string }
const rows = ref<Row[]>([]), opened = ref(false), busy = ref(false), message = ref('')
const selected = computed(() => rows.value.filter(row => row.selected && row.plan && ['ready','failed'].includes(row.state)))
const eligible = computed(() => rows.value.filter(row => row.plan && ['ready','failed'].includes(row.state)))
let generation = 0, controller: AbortController | null = null
function setBusy(value: boolean) { busy.value = value; emit('busy', value) }
function reset() { generation++; controller?.abort(); rows.value = []; message.value = ''; opened.value = false; setBusy(false) }
watch(() => currentUser.value?.id, reset)
onBeforeUnmount(reset)
function stop() { controller?.abort(); message.value = '已停止后续处理；当前已发出的上传可能已保存，重试不会重复创建。本地原件未删除。' }
async function inspect() {
  const owner = currentUser.value?.id
  if (!owner || props.disabled || busy.value) return
  const version = ++generation
  controller = new AbortController()
  const signal = controller.signal, valid = () => version === generation && owner === currentUser.value?.id && !signal.aborted
  opened.value = true; rows.value = []; message.value = '正在逐份检查，只读本地原件，尚未上传…'; setBusy(true)
  try {
    const sources = await listLocalSnapshotSources(owner)
    for (const source of sources) {
      if (!valid()) break
      const row: Row = { id: source.id, name: source.name, selected: false, state: 'ready', message: '' }
      try {
        const original = await readResearchSnapshot(source.id, owner)
        if (!valid()) break
        row.plan = (await prepareLocalMigration(original, owner)).plan
        row.name = row.plan.name
      } catch (error) { row.state = 'invalid'; row.message = error instanceof Error ? error.message : String(error) }
      if (valid()) rows.value.push(row)
    }
    if (valid()) message.value = sources.length ? `已检查 ${rows.value.length} 份，请选择要迁移的原档。` : '当前账户在此浏览器没有本地图表快照。已导出的多周期 JSON 可使用“导入研究备份”。'
  } catch (error) { if (valid()) message.value = error instanceof Error ? error.message : String(error) }
  finally { if (version === generation) setBusy(false) }
}
async function migrate() {
  const owner = currentUser.value?.id, batch = [...selected.value]
  if (!owner || props.disabled || busy.value || !batch.length) return
  const version = ++generation
  controller = new AbortController()
  const signal = controller.signal, valid = () => version === generation && owner === currentUser.value?.id && !signal.aborted
  setBusy(true); message.value = '按清单逐份上传；本地原件保持不变。'
  try {
    for (const row of batch) {
      if (!valid()) break
      row.state = 'uploading'; row.message = ''
      try {
        const saved = await uploadLocalMigration(row.plan!, owner, {
          read: readResearchSnapshot, valid,
          send: (id, body) => request<ArchiveRecord>(`/${id}`, { method: 'PUT', body, signal }),
        })
        if (!valid()) break
        row.state = saved.state === 'deleted' ? 'deleted' : 'saved'; row.selected = false
        row.message = saved.state === 'deleted' ? '云端已有副本在回收站中，未自动恢复。' : '已保存或已存在；云端后来编辑的备注不覆盖。'
      } catch (error) {
        if (version !== generation) break
        row.state = 'failed'; row.message = signal.aborted ? '本次等待已停止；服务器可能已保存，可用同一 ID 重试核查。' : error instanceof Error ? error.message : String(error)
        message.value = '本条未确认成功，已停止后续上传。可保留选择重试，或取消本条选择后继续；本地原件未删除。'
        break
      }
    }
    if (valid() && batch.every(row => ['saved','deleted'].includes(row.state))) message.value = '所选原档已核对完成；本地原件保留，没有重新计算。'
  } finally {
    if (version === generation) { setBusy(false); emit('finished') }
  }
}
const labels = { ready: '待确认', invalid: '不可迁移', uploading: '上传中', saved: '已在云端', deleted: '在回收站', failed: '待重试' }
const sizeLabel = (bytes: number) => bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1024 / 1024).toFixed(2)} MiB`
</script>
<template>
  <section class="local-migration" aria-label="本地快照迁移" :aria-busy="busy">
    <div class="migration-heading"><div><h4>本地快照迁移</h4><p>检查当前账户在此浏览器保存的图表快照，选择后复制到云端。</p></div><button :disabled="disabled || busy || !currentUser" @click="inspect">{{ opened ? '重新检查本地快照' : '检查本地快照' }}</button></div>
    <template v-if="opened">
      <p class="migration-note">不删除本地原件，不重算。相同原档重复迁移不会重复创建；不同内容保存为新副本。旧档缺少的指标不会补造，内容真实性未由服务器验证。</p>
      <p role="status" aria-live="polite">{{ message }}</p>
      <div v-if="rows.length" class="migration-list">
        <label class="migration-select-all"><input type="checkbox" :disabled="busy || disabled || !eligible.length" :checked="eligible.length > 0 && eligible.every(row => row.selected)" @change="eligible.forEach(row => row.selected = ($event.target as HTMLInputElement).checked)" />选择所有可迁移原档</label>
        <article v-for="row in rows" :key="row.id" class="migration-row">
          <label><input v-model="row.selected" type="checkbox" :disabled="busy || disabled || !row.plan || !['ready','failed'].includes(row.state)" :aria-label="`选择 ${row.name}`" /><span><strong>{{ row.name }}</strong><small v-if="row.plan">{{ row.plan.description }} · {{ sizeLabel(row.plan.bytes) }}</small></span></label>
          <span class="migration-state" :class="{failed: ['invalid','failed'].includes(row.state)}">{{ labels[row.state] }}</span>
          <p v-if="row.message" class="row-message">{{ row.message }}</p>
          <details v-if="row.plan?.warnings.length"><summary>原档说明</summary><p v-for="warning in row.plan.warnings" :key="warning">{{ warning }}</p></details>
        </article>
      </div>
      <div class="migration-actions"><button v-if="!busy" :disabled="disabled || !selected.length" @click="migrate">确认迁移 {{ selected.length }} 份到当前账户</button><button v-if="busy" @click="stop">停止后续处理</button><button v-else @click="opened=false;rows=[]">收起清单</button></div>
    </template>
  </section>
</template>
<style scoped>
.local-migration{margin:16px 0;padding:16px 0;border-block:1px solid var(--border);min-width:0}.migration-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.migration-heading>div{min-width:0}h4{margin:0;font-size:12px;font-weight:600}p{font-size:11px;color:var(--text-muted);line-height:1.8;overflow-wrap:anywhere;margin:8px 0}.migration-heading p{margin-bottom:0}button{background:var(--bg-elevated);color:var(--text-muted);border:1px solid var(--border);border-radius:7px;padding:6px 10px;min-height:32px;font:inherit;font-size:11px;cursor:pointer;transition:border-color .15s,color .15s}.migration-heading>button{flex-shrink:0}button:hover:not(:disabled){border-color:var(--accent);color:var(--text)}button:disabled{opacity:.5;cursor:default}.migration-select-all,.migration-row label{display:flex;align-items:center;gap:10px;font-size:11px;min-width:0}.migration-select-all{padding:10px 0}.migration-list{max-height:420px;overflow:auto;overscroll-behavior:contain}.migration-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px;padding:12px 0;border-top:1px solid var(--border)}input[type=checkbox]{width:15px;height:15px;flex-shrink:0;accent-color:var(--accent)}strong{font-size:12px;font-weight:500;overflow-wrap:anywhere}small{display:block;margin-top:4px;color:var(--text-muted);font-size:10px}.migration-state{font-size:10px;color:var(--text-muted);white-space:nowrap;align-self:center}.failed{color:var(--danger,#e9ab9f)}.row-message,.migration-row details{grid-column:1/-1;margin:0 0 0 25px}.migration-row details{font-size:11px;color:var(--text-muted)}summary{cursor:pointer;padding:3px 0}.migration-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:600px){.migration-heading{align-items:flex-start;flex-wrap:wrap}.migration-row{gap:8px}.migration-actions>button{min-height:36px}}@media(prefers-reduced-motion:reduce){button{transition:none}}
</style>
