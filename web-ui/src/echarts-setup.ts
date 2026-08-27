// ECharts 按需引入。只注册用到的图表类型，避免全量引入（~1MB → ~400KB）。
// 用到的：candlestick（K线）、line/bar（指标/净值）、markPoint/markLine（信号/阈值）、heatmap（寻优热力图）。

import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, HeatmapChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  CanvasRenderer,
  CandlestickChart,
  LineChart,
  BarChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  MarkPointComponent,
  MarkAreaComponent,
  MarkLineComponent,
  VisualMapComponent,
])

// A股惯例：红涨绿跌
export const UP_COLOR = '#ff5e68'
export const DOWN_COLOR = '#30d17b'

// 注册内联 dark 主题（echarts/core 不预置 'dark' 主题数据）。
// 覆盖坐标轴文字、分割线等默认浅色样式，适配深色背景。
echarts.registerTheme('dark', {
  backgroundColor: 'transparent',
  textStyle: { color: '#a6a6ad', fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' },
  title: { textStyle: { color: '#f5f5f7' }, subtextStyle: { color: '#a6a6ad' } },
  legend: { textStyle: { color: '#a6a6ad' } },
  tooltip: {
    backgroundColor: 'rgba(31,32,37,0.94)',
    borderColor: 'rgba(255,255,255,0.12)',
    textStyle: { color: '#f5f5f7' },
    extraCssText: 'backdrop-filter: blur(18px); border-radius: 10px; box-shadow: 0 14px 34px rgba(0,0,0,.38);',
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.09)' } },
    axisLabel: { color: '#686a73' },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { lineStyle: { color: 'rgba(255,255,255,0.09)' } },
    axisLabel: { color: '#686a73' },
    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.065)' } },
  },
})

export default echarts
