<script setup lang="ts">
import { computed, ref } from 'vue'
import { studyLabel, studyNumber as fmt, studySlope, studyStatus, type StudyRow } from '../research-study'
const props = defineProps<{ row: StudyRow }>()
const showAllEvents = ref(false)
const events = computed(() => props.row.events.slice().reverse())
const displayedEvents = computed(() => showAllEvents.value ? events.value : events.value.slice(0, 12))
const names = { ma: '价格均线', volume: '成交量均线', macd: 'MACD' } as const
const pairNames = { ma: ['MA5', 'MA10'], volume: ['MAVOL5', 'MAVOL10'], macd: ['DIF', 'DEA'] }
</script>

<template>
  <div class="context-detail">
    <section class="context-section">
      <h4>近期走势 <span>{{ row.window.count }} 根已收盘</span></h4>
      <p class="context-lead">{{ row.recent.summary }}</p>
      <dl class="context-stats">
        <div><dt>区间涨跌</dt><dd>{{ fmt(row.recent.change_pct) }}%</dd></div>
        <div><dt>区间最高 / 最低</dt><dd>{{ fmt(row.recent.high) }} / {{ fmt(row.recent.low) }}</dd></div>
        <div><dt>收盘最大回撤</dt><dd>{{ fmt(row.recent.max_close_drawdown_pct) }}%</dd></div>
      </dl>
      <details class="reading-disclosure"><summary>区间与判断口径</summary>
        <p>{{ row.window.start }} — {{ row.window.end }}；窗口前 {{ row.window.warmup_bars }} 根参与指标预热。</p>
        <p>{{ row.recent.method }}</p><p v-if="row.window.truncated">可用历史未覆盖所请求的完整区间，以上只描述实际取得的行情。</p>
      </details>
    </section>
    <section class="context-section">
      <h4>均线排列范围 <span>不受图形显隐影响</span></h4>
      <p class="context-lead">多头{{ row.ma_research.bull.to ? `至 MA${row.ma_research.bull.to}` : '未排列' }} · 空头{{ row.ma_research.bear.to ? `至 MA${row.ma_research.bear.to}` : '未排列' }}</p>
      <p class="context-muted">多头：{{ row.ma_research.bull.reason }}；空头：{{ row.ma_research.bear.reason }}</p>
      <div class="context-table-scroll"><table><thead><tr><th>均线</th><th>数值</th><th>方向</th><th>每根变化</th></tr></thead><tbody>
        <tr v-for="line in row.ma_research.lines" :key="line.period"><th>MA{{ line.period }}</th><td :title="String(line.value)">{{ fmt(line.value) }}</td><td>{{ studySlope(line.slope) }}</td><td :title="String(line.slope)">{{ fmt(line.slope) }}</td></tr>
      </tbody></table></div>
      <details class="reading-disclosure"><summary>相邻均线的间距</summary><p v-for="gap in row.ma_research.gaps" :key="gap.fast">MA{{ gap.fast }} / MA{{ gap.slow }}：差值 {{ fmt(gap.gap) }}；差值变化 {{ fmt(gap.gap_change) }}</p></details>
    </section>
    <section class="context-section">
      <h4>量价与动能</h4>
      <div v-for="(name, key) in names" :key="key" class="context-pair">
        <h5>{{ name }}</h5><div><p>{{ row.pairs[key].description }}</p><p class="context-muted">{{ row.pairs[key].directions }} · 当前相对位置持续 {{ row.pairs[key].position_bars }} 根</p>
        <dl class="context-stats"><div><dt>{{ pairNames[key][0] }} / {{ pairNames[key][1] }}</dt><dd>{{ fmt(row.pairs[key].fast) }} / {{ fmt(row.pairs[key].slow) }}</dd></div><div v-if="key !== 'macd'"><dt>相对间距</dt><dd>{{ fmt(row.pairs[key].relative_gap) }}{{ row.pairs[key].relative_gap == null ? '' : '%' }}</dd></div></dl>
        <p v-if="key === 'ma'" class="context-muted">已连续 {{ row.pairs.ma.above_ma5_bars }} 根收盘在 MA5 上方，{{ row.pairs.ma.above_ma10_bars }} 根在 MA10 上方。</p>
        <p v-if="key === 'macd'" class="context-muted">{{ row.axis }} · {{ row.histogram }} · 同色柱连续缩短 {{ row.histogram_shrinking_bars }} 根</p>
        <details class="reading-disclosure"><summary>未舍入数值</summary><p>{{ pairNames[key][0] }}：{{ row.pairs[key].fast ?? '不可计算' }}；{{ pairNames[key][1] }}：{{ row.pairs[key].slow ?? '不可计算' }}</p><p>原始差值：{{ row.pairs[key].gap ?? '不可计算' }}；差值变化：{{ row.pairs[key].gap_change ?? '不可计算' }}</p></details>
        </div>
      </div>
    </section>
    <section class="context-section">
      <h4>本窗口内的配合过程</h4><p class="context-lead">{{ row.coordination.summary }}</p>
      <dl class="context-lines"><div v-for="part in row.coordination.components" :key="part.key"><dt>{{ part.label }}</dt><dd>{{ part.description }}<small v-if="part.date">最近有效事件 {{ part.date }}</small></dd></div></dl>
      <details class="reading-disclosure"><summary>修复、破坏与过轴记录 <span>{{ events.length }} 项</span></summary>
        <p v-if="!events.length">窗口内没有新的交叉或修复变化；不推断窗口之前的事件。</p>
        <ol class="context-events"><li v-for="(event, i) in displayedEvents" :key="i"><time>{{ event.date }}</time><div><strong>{{ event.label }}</strong><p>{{ event.active ? '当前仍有效' : `已中断 · ${event.invalidated_at}` }} · {{ event.bars_ago }} 根前</p><small v-if="event.known_at">收盘可知 {{ event.known_at }}</small></div></li></ol>
        <button v-if="events.length > 12" class="context-text-button" @click="showAllEvents = !showAllEvents">{{ showAllEvents ? '收起较早记录' : `显示全部 ${events.length} 项` }}</button>
      </details>
    </section>
    <section class="context-section">
      <h4>严格笔与当前方向 <span>观察不替代成笔</span></h4>
      <dl class="context-lines"><div><dt>严格笔事实</dt><dd v-if="row.direction_observation.strict">{{ row.direction_observation.strict.direction === 'up' ? '向上' : '向下' }} · {{ row.direction_observation.strict.locked ? '已被反向笔锁定' : '末端可延伸' }}<small>{{ row.direction_observation.strict.start_date }} → {{ row.direction_observation.strict.end_date }} · {{ fmt(row.direction_observation.strict.start_price) }} → {{ fmt(row.direction_observation.strict.end_price) }}</small></dd><dd v-else>尚无严格笔</dd></div>
        <div><dt>当前尾段</dt><dd>{{ row.direction_observation.description }}<small v-if="row.direction_observation.anchor_date">观察极值 {{ row.direction_observation.anchor_date }} · {{ fmt(row.direction_observation.anchor_price) }}；分型可知 {{ row.direction_observation.known_date }}</small></dd></div>
        <div><dt>后续确认</dt><dd>{{ row.direction_observation.confirmation }}</dd></div><div><dt>撤销条件</dt><dd>{{ row.direction_observation.invalidation }}</dd></div>
      </dl>
      <details class="reading-disclosure"><summary>小周期辅助依据 <span>{{ row.direction_observation.auxiliary.length }} 个周期</span></summary>
        <p v-if="!row.direction_observation.auxiliary.length">尚未选择更小周期。可在上方勾选后更新研究，不推断缺失行情。</p>
        <div v-for="child in row.direction_observation.auxiliary" :key="child.category" class="context-child"><strong>{{ studyLabel(child.category) }}</strong><p>{{ child.description }}</p><p class="context-muted">当前尾段：{{ child.tail }}；{{ child.coordination }}</p><p class="context-muted">{{ child.axis }} · {{ child.recent }} · 收盘截止 {{ child.last_closed_at }}</p><p v-for="d in child.divergences" :key="`${d.date}-${d.status}`">{{ d.date }} {{ d.direction === 'up' ? '顶' : '底' }}背离 · {{ studyStatus(d.status) }}</p></div>
      </details>
      <details class="reading-disclosure"><summary>本级背离与方向变化记录</summary>
        <p v-for="(d, i) in row.divergences" :key="i">{{ d.date }} {{ d.direction === 'up' ? '顶' : '底' }}背离 · {{ studyStatus(d.status) }}<span v-if="d.confirmed_date"> · 确认 {{ d.confirmed_date }}</span></p>
        <p v-if="!row.divergences.length">暂无有效背离记录，不作为反转已确认的依据。</p>
        <ol class="context-events"><li v-for="(event, i) in row.direction_observation.history.slice().reverse()" :key="i"><time>{{ event.date }}</time><div><strong>{{ event.description }}</strong><small>观察端点 {{ event.anchor_date ?? '尚未出现' }}</small></div></li></ol>
      </details>
    </section>
    <details v-if="row.observations.length" class="reading-disclosure"><summary>其他辅助观察</summary><p v-for="note in row.observations" :key="note">{{ note }}</p></details>
  </div>
</template>

<style scoped>
.context-detail{padding:0 18px 18px}.context-section{padding:20px 0;border-bottom:1px solid var(--border)}.context-section:last-of-type{border-bottom:0}h4{margin:0 0 12px;font-size:13px;font-weight:600}h4 span{font-size:11px;color:var(--text-muted);font-weight:400;margin-left:12px}p{font-size:12px;line-height:1.8;margin:7px 0;overflow-wrap:anywhere}.context-lead{color:var(--text);font-size:13px}.context-muted,small{color:var(--text-muted)}small{display:block;font-size:11px;line-height:1.8}.context-stats{display:flex;flex-wrap:wrap;gap:14px 32px;margin:14px 0}.context-stats div{min-width:90px}.context-stats dt{font-size:11px;color:var(--text-muted);margin-bottom:5px}.context-stats dd{margin:0;font-size:13px;font-variant-numeric:tabular-nums}.context-table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums}th,td{padding:9px 12px;border-bottom:1px solid var(--border);text-align:right}th:first-child{text-align:left}thead th{color:var(--text-muted);font-size:11px;font-weight:500}tbody th{font-weight:500}.context-pair{display:grid;grid-template-columns:110px minmax(0,1fr);gap:18px;padding:14px 0;border-bottom:1px solid var(--border)}.context-pair:last-child{border:0}.context-pair h5{font-size:12px;font-weight:500;margin:8px 0}.context-lines{margin:0}.context-lines>div{display:grid;grid-template-columns:110px minmax(0,1fr);gap:18px;margin:12px 0;font-size:12px;line-height:1.8}.context-lines dt{color:var(--text-muted)}.context-lines dd{margin:0}.context-events{list-style:none;padding:0;margin:12px 0}.context-events li{display:grid;grid-template-columns:145px minmax(0,1fr);gap:16px;padding:10px 0;border-bottom:1px solid var(--border);font-size:12px}.context-events time{font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums}.context-events strong{font-weight:500}.context-events p{font-size:11px;margin:3px 0}.context-text-button{background:none;border:0;color:var(--accent,#79b9ef);padding:8px 0;font-size:12px;cursor:pointer}.context-child{padding:12px 0;border-bottom:1px solid var(--border);font-size:12px}.reading-disclosure{margin-top:14px}.reading-disclosure>summary{font-size:12px;cursor:pointer}.reading-disclosure>summary span{font-size:11px;color:var(--text-muted);margin-left:10px}@media(max-width:600px){.context-detail{padding:0 12px 14px}.context-pair,.context-lines>div{grid-template-columns:1fr;gap:3px}.context-events li{grid-template-columns:1fr;gap:4px}h4 span{display:block;margin:5px 0 0}.context-stats{gap:12px 20px}th,td{padding:8px}.context-section{padding:16px 0}}
</style>
