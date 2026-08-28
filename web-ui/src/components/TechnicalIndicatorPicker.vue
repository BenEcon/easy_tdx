<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  INDICATOR_CATEGORIES,
  QUICK_INDICATORS,
  TECHNICAL_INDICATORS,
  getIndicatorDefinition,
  type IndicatorParams,
  type TechnicalIndicator,
} from '../technical-indicators'

const props = withDefaults(defineProps<{
  modelValue: TechnicalIndicator
  params?: IndicatorParams
  loading?: boolean
  error?: string
}>(), { params: () => ({}), loading: false, error: '' })
const emit = defineEmits<{
  'update:modelValue': [value: TechnicalIndicator]
  'update:params': [value: IndicatorParams]
}>()

const showLibrary = ref(false)
const query = ref('')
const category = ref('全部')
const draftParams = ref<IndicatorParams>({})

const current = computed(() => getIndicatorDefinition(props.modelValue))
const quickItems = computed(() => QUICK_INDICATORS.map(getIndicatorDefinition))
const filtered = computed(() => {
  const normalized = query.value.trim().toLowerCase()
  return TECHNICAL_INDICATORS.slice(2).filter((entry) => {
    const categoryMatch = category.value === '全部' || entry.category === category.value
    const text = `${entry.code} ${entry.label} ${entry.fullName} ${entry.description}`.toLowerCase()
    return categoryMatch && (!normalized || text.includes(normalized))
  })
})

function paramsFor(value: TechnicalIndicator): IndicatorParams {
  const definition = getIndicatorDefinition(value)
  return value === props.modelValue
    ? { ...definition.defaultParams, ...props.params }
    : { ...definition.defaultParams }
}

function choose(value: TechnicalIndicator) {
  const nextParams = paramsFor(value)
  emit('update:modelValue', value)
  emit('update:params', nextParams)
  draftParams.value = nextParams
}

function openLibrary() {
  query.value = ''
  category.value = '全部'
  draftParams.value = paramsFor(props.modelValue)
  showLibrary.value = true
}

function selectFromLibrary(value: TechnicalIndicator) {
  choose(value)
  draftParams.value = paramsFor(value)
}

function applyParams() {
  emit('update:params', { ...draftParams.value })
  showLibrary.value = false
}

watch(() => props.params, (value) => {
  if (showLibrary.value) draftParams.value = { ...current.value.defaultParams, ...value }
}, { deep: true })
</script>

<template>
  <div class="indicator-control">
    <div class="indicator-heading">
      <span class="indicator-dot" :class="{ busy: loading }"></span>
      <div><strong>技术指标</strong><small>{{ loading ? '正在计算…' : error || current.description }}</small></div>
    </div>
    <div class="indicator-actions">
      <div class="indicator-options" role="radiogroup" aria-label="常用技术指标">
        <button
          v-for="entry in quickItems"
          :key="entry.value"
          type="button"
          role="radio"
          :aria-checked="modelValue === entry.value"
          :class="{ active: modelValue === entry.value }"
          @click="choose(entry.value)"
        >{{ entry.label }}</button>
      </div>
      <button class="library-button" type="button" @click="openLibrary">
        <span>{{ QUICK_INDICATORS.includes(modelValue) ? '全部指标' : current.label }}</span>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 5.5h10M3 8h10M3 10.5h10" /></svg>
      </button>
    </div>

    <Teleport to="body">
      <Transition name="indicator-modal">
        <div v-if="showLibrary" class="indicator-backdrop" @click.self="showLibrary = false" @keydown.esc.window="showLibrary = false">
          <section class="indicator-modal-card" role="dialog" aria-modal="true" aria-labelledby="indicator-library-title">
            <header class="modal-head">
              <div><span>图表工具</span><h3 id="indicator-library-title">技术指标库</h3><p>选择一个指标叠加到主图或显示在独立副图中。</p></div>
              <button class="modal-close" aria-label="关闭" @click="showLibrary = false"><svg viewBox="0 0 18 18"><path d="m5 5 8 8M13 5l-8 8" /></svg></button>
            </header>
            <div class="library-tools">
              <label class="indicator-search"><span>搜索指标</span><input v-model="query" type="search" placeholder="中文名称或代码，如：布林带、ATR" autofocus /></label>
              <div class="category-tabs">
                <button v-for="entry in INDICATOR_CATEGORIES" :key="entry" :class="{ active: category === entry }" @click="category = entry">{{ entry }}</button>
              </div>
            </div>
            <div class="library-body">
              <div class="indicator-list">
                <button
                  v-for="entry in filtered"
                  :key="entry.value"
                  :class="{ selected: modelValue === entry.value }"
                  @click="selectFromLibrary(entry.value)"
                >
                  <span class="indicator-code">{{ entry.code }}</span>
                  <span class="indicator-copy"><strong>{{ entry.fullName }}</strong><small>{{ entry.description }}</small></span>
                  <span class="placement-tag">{{ entry.placement === 'overlay' ? '主图' : '副图' }}</span>
                </button>
                <div v-if="!filtered.length" class="empty-indicators">没有找到对应指标</div>
              </div>
              <aside class="indicator-detail">
                <span class="detail-category">{{ current.category }} · {{ current.placement === 'overlay' ? '叠加主图' : current.placement === 'panel' ? '独立副图' : '无指标' }}</span>
                <h4>{{ current.fullName }}</h4>
                <code>{{ current.code }}</code>
                <p>{{ current.description }}</p>
                <div v-if="current.outputs.length" class="output-list">
                  <small>输出曲线</small><div><span v-for="output in current.outputs" :key="output">{{ output.replace(`${current.code}_`, '') }}</span></div>
                </div>
                <div v-if="Object.keys(current.defaultParams).length" class="param-editor">
                  <small>参数设置</small>
                  <label v-for="(_, key) in current.defaultParams" :key="key"><span>{{ key }}</span><input v-model.number="draftParams[key]" type="number" step="any" /></label>
                </div>
                <p v-else class="no-params">该指标无需调整参数</p>
                <button class="primary apply-button" @click="applyParams">应用指标</button>
              </aside>
            </div>
          </section>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.indicator-control{display:flex;min-height:48px;align-items:center;justify-content:space-between;gap:16px;margin-top:8px;padding:8px 10px 8px 13px;border-top:1px solid rgba(255,255,255,.075)}.indicator-heading{display:flex;min-width:0;align-items:center;gap:9px}.indicator-heading>div{display:flex;min-width:0;flex-direction:column;gap:1px}.indicator-heading strong{color:#b5b6bd;font-size:10px;font-weight:680}.indicator-heading small{max-width:260px;overflow:hidden;color:#646771;font-size:9px;text-overflow:ellipsis;white-space:nowrap}.indicator-dot{width:6px;height:6px;flex:0 0 auto;background:#3a8ff5;border-radius:50%;box-shadow:0 0 0 3px rgba(58,143,245,.1)}.indicator-dot.busy{animation:pulse 1s ease infinite}.indicator-actions{display:flex;align-items:center;gap:6px}.indicator-options{display:inline-flex;align-items:center;gap:2px;padding:3px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);border-radius:9px}.indicator-options button,.library-button{min-height:27px;padding:0 9px;color:#777982;background:transparent;border-color:transparent;border-radius:6px;box-shadow:none;font-size:9px;font-weight:620}.indicator-options button:hover{color:#c8c8cd;background:rgba(255,255,255,.045)}.indicator-options button.active{color:#f5f5f7;background:rgba(10,132,255,.2);border-color:rgba(64,158,255,.35);box-shadow:0 1px 0 rgba(255,255,255,.07) inset,0 3px 10px rgba(0,0,0,.16)}.library-button{display:flex;align-items:center;gap:5px;color:#9b9da6;background:rgba(255,255,255,.035);border-color:rgba(255,255,255,.075)}.library-button:hover{color:#f1f1f4;background:rgba(255,255,255,.07)}.library-button svg{width:12px;height:12px}.library-button path{fill:none;stroke:currentColor;stroke-linecap:round;stroke-width:1.25}
.indicator-backdrop{position:fixed;z-index:350;inset:0;display:grid;padding:24px;place-items:center;background:rgba(4,5,8,.68);backdrop-filter:blur(13px);-webkit-backdrop-filter:blur(13px)}.indicator-modal-card{display:flex;width:min(940px,calc(100vw - 40px));height:min(690px,calc(100vh - 48px));min-height:480px;flex-direction:column;overflow:hidden;background:linear-gradient(145deg,rgba(40,42,50,.985),rgba(20,21,26,.995));border:1px solid rgba(255,255,255,.13);border-radius:20px;box-shadow:0 30px 100px rgba(0,0,0,.58),0 0 0 1px rgba(0,0,0,.2)}.modal-head{display:flex;align-items:flex-start;justify-content:space-between;padding:20px 23px 16px;border-bottom:1px solid rgba(255,255,255,.075)}.modal-head span,.detail-category{color:#6daeff;font-size:8px;font-weight:760;letter-spacing:.14em}.modal-head h3{margin-top:3px;font-size:18px}.modal-head p{margin-top:3px;color:#737680;font-size:10px}.modal-close{display:grid;width:32px;height:32px;min-height:32px;padding:0;place-items:center;color:#858791;background:rgba(255,255,255,.035);border-color:rgba(255,255,255,.08);border-radius:50%;box-shadow:none}.modal-close:hover{color:#fff;background:rgba(255,255,255,.09)}.modal-close svg{width:15px}.modal-close path{fill:none;stroke:currentColor;stroke-linecap:round;stroke-width:1.4}.library-tools{padding:13px 18px 10px;background:rgba(0,0,0,.09);border-bottom:1px solid rgba(255,255,255,.07)}.indicator-search{display:flex;flex-direction:column;gap:5px}.indicator-search span{color:#737680;font-size:9px}.indicator-search input{width:100%;height:37px;padding:0 12px;color:#f1f1f4;background:rgba(0,0,0,.22);border:1px solid rgba(255,255,255,.11);border-radius:9px;outline:0}.indicator-search input:focus{border-color:rgba(10,132,255,.7);box-shadow:0 0 0 3px rgba(10,132,255,.12)}.category-tabs{display:flex;gap:4px;margin-top:9px;overflow-x:auto}.category-tabs button{min-height:25px;padding:0 9px;color:#737680;background:transparent;border-color:transparent;border-radius:7px;box-shadow:none;font-size:8px}.category-tabs button:hover{color:#bbbcc3;background:rgba(255,255,255,.04)}.category-tabs button.active{color:#dcecff;background:rgba(10,132,255,.15);border-color:rgba(10,132,255,.23)}.library-body{display:grid;min-height:0;flex:1;grid-template-columns:minmax(0,1fr) 280px}.indicator-list{min-height:0;padding:9px;overflow-y:auto}.indicator-list>button{display:grid;width:100%;min-height:54px;grid-template-columns:72px minmax(0,1fr) auto;gap:10px;align-items:center;padding:8px 10px;color:#a3a5ad;background:transparent;border-color:transparent;border-radius:10px;box-shadow:none;text-align:left}.indicator-list>button:hover{background:rgba(255,255,255,.038)}.indicator-list>button.selected{background:linear-gradient(90deg,rgba(10,132,255,.16),rgba(94,92,230,.07));border-color:rgba(72,157,255,.25)}.indicator-code{color:#73b4ff;font:10px var(--font-mono);font-weight:700}.indicator-copy{display:flex;min-width:0;flex-direction:column;gap:2px}.indicator-copy strong{color:#d4d4da;font-size:11px}.indicator-copy small{overflow:hidden;color:#696c75;font-size:9px;text-overflow:ellipsis;white-space:nowrap}.placement-tag{padding:2px 6px;color:#737680;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);border-radius:5px;font-size:8px}.indicator-detail{display:flex;min-height:0;flex-direction:column;padding:19px;background:rgba(0,0,0,.13);border-left:1px solid rgba(255,255,255,.07);overflow-y:auto}.indicator-detail h4{margin-top:6px;color:#f3f3f6;font-size:17px;line-height:1.35}.indicator-detail>code{margin-top:4px;color:#81848e;font:9px var(--font-mono)}.indicator-detail>p{margin-top:12px;color:#94969f;font-size:10px;line-height:1.7}.output-list,.param-editor{margin-top:18px;padding-top:14px;border-top:1px solid rgba(255,255,255,.07)}.output-list>small,.param-editor>small{display:block;margin-bottom:8px;color:#777a84;font-size:8px;font-weight:700;letter-spacing:.09em}.output-list>div{display:flex;flex-wrap:wrap;gap:5px}.output-list span{padding:3px 6px;color:#aeb0b8;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.075);border-radius:5px;font:8px var(--font-mono)}.param-editor label{display:grid;grid-template-columns:1fr 100px;align-items:center;gap:8px;margin-top:7px}.param-editor label span{color:#8d8f98;font:9px var(--font-mono)}.param-editor input{height:30px;padding:0 8px;text-align:right}.indicator-detail .no-params{color:#656872;font-size:9px}.apply-button{min-height:36px;margin-top:auto}.empty-indicators{display:grid;min-height:180px;place-items:center;color:#737680;font-size:10px}.indicator-modal-enter-active,.indicator-modal-leave-active{transition:opacity .18s ease}.indicator-modal-enter-active .indicator-modal-card,.indicator-modal-leave-active .indicator-modal-card{transition:transform .18s ease,opacity .18s ease}.indicator-modal-enter-from,.indicator-modal-leave-to{opacity:0}.indicator-modal-enter-from .indicator-modal-card,.indicator-modal-leave-to .indicator-modal-card{opacity:0;transform:translateY(8px) scale(.985)}@keyframes pulse{50%{opacity:.4;transform:scale(.8)}}
@media(max-width:760px){.indicator-control{align-items:flex-start;flex-direction:column;gap:7px}.indicator-actions{width:100%;overflow-x:auto}.indicator-options{flex:0 0 auto}.indicator-backdrop{padding:8px}.indicator-modal-card{width:100%;height:calc(100vh - 16px);border-radius:15px}.library-body{grid-template-columns:1fr}.indicator-detail{display:none}.indicator-list>button{grid-template-columns:65px minmax(0,1fr) auto}}
</style>
