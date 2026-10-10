<script setup lang="ts">
import { nextTick } from 'vue'
import { researchWorkspaces, workspaceFromKey, type ResearchWorkspace } from '../research-workspace'
const props = defineProps<{ modelValue: ResearchWorkspace; mobile: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ResearchWorkspace] }>()
const buttons = new Map<ResearchWorkspace, HTMLButtonElement>()
async function keydown(event: KeyboardEvent) {
  const next = workspaceFromKey(props.modelValue,event.key)
  if (!next || event.metaKey || event.ctrlKey || event.altKey) return
  event.preventDefault(); emit('update:modelValue',next)
  await nextTick(); buttons.get(next)?.focus({preventScroll:true})
}
</script>
<template>
  <nav class="research-workspace-nav" :class="{mobile}" aria-label="缠论工作区" @keydown="keydown">
    <button v-for="item in researchWorkspaces" :key="item.value" :ref="el => { if (el) buttons.set(item.value,el as HTMLButtonElement) }"
      type="button" :aria-pressed="modelValue === item.value" @click="emit('update:modelValue',item.value)">
      <strong>{{ item.label }}</strong><span>{{ item.description }}</span>
    </button>
  </nav>
</template>
<style scoped>
.research-workspace-nav{position:sticky;top:0;z-index:15;display:flex;gap:4px;padding:8px 20px;background:var(--bg-panel,#1c1e23);border-bottom:1px solid var(--border)}button{display:flex;align-items:baseline;gap:9px;padding:10px 14px;border:1px solid transparent;border-radius:8px;background:transparent;color:var(--text-muted);cursor:pointer;transition:background .15s,border-color .15s;white-space:nowrap}button strong{font-size:12px;font-weight:550}button span{font-size:10px}button[aria-pressed=true]{color:var(--text);background:rgba(78,150,224,.09);border-color:rgba(100,157,219,.2)}button[aria-pressed=true] strong{color:var(--accent)}button:hover{background:rgba(128,128,128,.08)}button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}.mobile{position:fixed;top:auto;bottom:calc(10px + env(safe-area-inset-bottom));left:12px;right:12px;border:1px solid var(--border);border-radius:12px;padding:5px;box-shadow:0 4px 20px #0004}.mobile button{flex:1;justify-content:center;min-height:42px;padding:8px}.mobile button span{display:none}@media(prefers-reduced-motion:reduce){button{transition:none}}
</style>
