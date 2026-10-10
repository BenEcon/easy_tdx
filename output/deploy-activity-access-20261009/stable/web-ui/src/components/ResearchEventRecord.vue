<script setup lang="ts">
import { computed } from 'vue'
import { structureDate } from '../structure-display'

const props = defineProps<{
  title: string
  date?: string | null
  dateLabel?: string
  tone: 'buy' | 'sell' | 'bottom' | 'top' | 'nonstandard'
  state?: string
  stateLabel: string
  metadata: Array<{ label: string; value?: string | null }>
  description?: string
  note?: string
}>()
const dateText = computed(() => structureDate(props.date))
const dateParts = computed(() => /^(\d{4})-(\d{2}-\d{2})(?: (.*))?$/.exec(dateText.value))
</script>

<template>
  <article class="research-event" :class="[tone, state]">
    <div class="event-date-rail">
      <span>{{ dateLabel || '极值日期' }}</span>
      <time :datetime="date || undefined" :aria-label="dateText">
        <template v-if="dateParts"><small>{{ dateParts[1] }}</small><strong>{{ dateParts[2] }}</strong><small v-if="dateParts[3]">{{ dateParts[3] }}</small></template>
        <strong v-else>{{ dateText }}</strong>
      </time>
    </div>
    <div class="event-content">
      <header class="event-heading"><h4><i aria-hidden="true"></i>{{ title }}</h4><span class="event-status"><i aria-hidden="true"></i>{{ stateLabel }}</span></header>
      <dl v-if="metadata.length" class="event-metadata"><div v-for="field in metadata" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value || '—' }}</dd></div></dl>
      <p v-if="note" class="event-note">{{ note }}</p>
      <p v-if="description" class="event-description">{{ description }}</p>
      <slot />
    </div>
  </article>
</template>

<style scoped>
.research-event { --event-color: #caa1e4; display: grid; grid-template-columns: 84px minmax(0,1fr); gap: 24px; min-width: 0; padding: 24px 0; border-bottom: 1px solid rgba(255,255,255,.065); }
.research-event:last-child { border-bottom: 0; }
.research-event.buy, .research-event.nonstandard { --event-color: #e89ca4; }
.research-event.sell, .research-event.top { --event-color: #8ac9ac; }
.research-event.superseded { --event-color: #9ba4b2; }
.event-date-rail { color: #8e9aab; font-variant-numeric: tabular-nums; }
.event-date-rail > span { display: block; margin-bottom: 10px; font-size: 10px; }
.event-date-rail time { display: flex; flex-direction: column; gap: 4px; }
.event-date-rail small { font-size: 10px; line-height: 1.7; }
.event-date-rail strong { color: #cbd3df; font-size: 19px; font-weight: 450; letter-spacing: -.035em; line-height: 1.3; }
.event-content { min-width: 0; }
.event-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px 16px; }
.event-heading h4 { display: inline-flex; align-items: baseline; gap: 9px; margin: 0; color: var(--event-color); font-size: 13px; font-weight: 550; line-height: 1.8; overflow-wrap: anywhere; }
.event-heading h4 i { width: 6px; height: 6px; flex: 0 0 6px; border: 1px solid currentColor; border-radius: 2px; transform: rotate(45deg); background: currentColor; }
.candidate h4 i, .superseded h4 i { background: transparent; }
.event-status { display: inline-flex; align-items: center; gap: 6px; color: #9ba7b7; font-size: 10px; line-height: 1.8; }
.event-status i { width: 4px; height: 4px; border: 1px solid currentColor; border-radius: 50%; }
.confirmed .event-status { color: #a7c6b7; }
.confirmed .event-status i { background: currentColor; }
.candidate .event-status { color: #cbb38b; }
.event-metadata { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(145px,100%),1fr)); gap: 12px 24px; margin: 14px 0; padding: 12px 0; border-top: 1px solid rgba(255,255,255,.035); border-bottom: 1px solid rgba(255,255,255,.035); font-variant-numeric: tabular-nums; }
.event-metadata > div { min-width: 0; }
.event-metadata dt { color: #8996a8; font-size: 10px; margin-bottom: 5px; }
.event-metadata dd { margin: 0; color: #c1ccda; font-size: 11px; line-height: 1.8; overflow-wrap: anywhere; }
.event-description, .event-note { margin: 10px 0; color: #aeb9c8; font-size: 12px; line-height: 1.95; text-align: justify; text-align-last: left; overflow-wrap: anywhere; }
.event-note { color: #bda987; font-size: 11px; }
.event-content :deep(.reading-disclosure > summary) { justify-content: space-between; padding: 9px 0; border-radius: 0; color: #a8bbd2; font-size: 11px; }
.event-content :deep(.reading-disclosure > summary::before) { display: none; }
.event-content :deep(.reading-disclosure > summary::after) { content: ''; width: 5px; height: 5px; flex: 0 0 5px; margin-right: 4px; border-right: 1px solid #94a4ba; border-bottom: 1px solid #94a4ba; transform: rotate(-45deg); transition: transform 150ms ease; }
.event-content :deep(.reading-disclosure[open] > summary::after) { transform: rotate(45deg); }
.event-content :deep(.audit-evidence-body) { padding: 6px 0 8px; }
.event-content :deep(.event-replays) { margin-top: 12px; }
.event-content :deep(.confirmation-replay) { display: grid; grid-template-columns: minmax(0,1fr) auto auto; gap: 8px; margin: 0; padding: 10px 0; border-top: 1px solid rgba(255,255,255,.05); }
.event-content :deep(.confirmation-replay > span) { font-size: 10px; color: #9caabc; }
.event-content :deep(.confirmation-replay button) { box-shadow: none; min-height: 30px; background: rgba(255,255,255,.025); border-color: rgba(160,180,207,.14); }
@container (max-width: 560px) {
  .research-event { grid-template-columns: minmax(0,1fr); gap: 12px; padding-block: 20px; }
  .event-date-rail { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 14px; }
  .event-date-rail > span { margin: 0; }
  .event-date-rail time { flex-direction: row; flex-wrap: wrap; align-items: baseline; gap: 6px; }
  .event-date-rail strong { font-size: 14px; }
  .event-metadata { gap: 12px; }
  .event-content :deep(.confirmation-replay) { grid-template-columns: minmax(0,1fr) minmax(0,1fr); }
  .event-content :deep(.confirmation-replay > span) { grid-column: 1 / -1; }
  .event-content :deep(.confirmation-replay button) { white-space: normal; min-height: 36px; }
}
@media (prefers-reduced-motion: reduce) { .event-content :deep(.reading-disclosure > summary::after) { transition: none; } }
</style>
