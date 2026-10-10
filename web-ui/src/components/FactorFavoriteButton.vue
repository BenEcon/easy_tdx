<script setup lang="ts">
defineProps<{name:string;active:boolean;busy?:boolean}>()
defineEmits<{toggle:[]}>()
</script>
<template><button type="button" class="factor-favorite" :aria-label="`${active?'取消收藏':'收藏'}${name}`" :title="active?'取消收藏':'收藏因子'" :aria-pressed="active" :disabled="busy" @click="$emit('toggle')"><span aria-hidden="true">{{ active?'★':'☆' }}</span></button></template>
<style scoped>.factor-favorite{flex:0 0 30px;min-height:30px;width:30px;padding:0;border:0;border-radius:6px;background:transparent;color:var(--text-muted);font-size:18px;line-height:1;cursor:pointer;transition:background .15s}.factor-favorite[aria-pressed=true]{color:var(--accent)}.factor-favorite:hover{background:var(--bg-hover)}.factor-favorite:disabled{opacity:.5;cursor:wait}.factor-favorite:focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(prefers-reduced-motion:reduce){.factor-favorite{transition:none}}</style>
