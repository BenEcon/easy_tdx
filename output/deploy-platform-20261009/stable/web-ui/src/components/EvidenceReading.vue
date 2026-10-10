<script setup lang="ts">
import { computed } from 'vue'
import { evidenceReadingRows } from '../evidence-reading'
const props = defineProps<{ lines: string[] }>()
const rows = computed(() => evidenceReadingRows(props.lines))
</script>

<template>
  <div class="evidence-reading">
    <template v-for="(row, index) in rows" :key="index">
      <dl v-if="row.label" class="evidence-field"><dt>{{ row.label }}</dt><dd>{{ row.text }}</dd></dl>
      <p v-else class="evidence-paragraph">{{ row.text }}</p>
    </template>
  </div>
</template>

<style scoped>
.evidence-reading { container-type: inline-size; min-width: 0; }
.evidence-reading .evidence-field { display: grid; grid-template-columns: 104px minmax(0,1fr); gap: 8px 18px; margin: 0; padding: 11px 0; border-bottom: 1px solid rgba(255,255,255,.04); font-size: 11px; line-height: 1.9; }
.evidence-field dt { color: #95a3b7; font-size: 10px; overflow-wrap: anywhere; }
.evidence-field dd { margin: 0; color: #c1ccda; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; text-align: left; }
.evidence-reading .evidence-paragraph { margin: 0; padding: 11px 0; color: #a7b4c5; font-size: 11px; line-height: 1.95; overflow-wrap: anywhere; text-align: justify; text-align-last: left; }
.evidence-reading > :last-child { border-bottom: 0; }
@container (max-width: 360px) {
  .evidence-reading .evidence-field { grid-template-columns: minmax(0,1fr); gap: 3px; padding-block: 10px; }
}
</style>
