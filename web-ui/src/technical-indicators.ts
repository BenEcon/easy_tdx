import { computeIndicators } from './api'
import type { Bar } from './types'

export type TechnicalIndicator = string
export type IndicatorParams = Record<string, number>
export type IndicatorPlacement = 'none' | 'panel' | 'overlay'

export interface IndicatorDefinition {
  value: TechnicalIndicator
  code: string
  label: string
  fullName: string
  category: string
  description: string
  outputs: string[]
  defaultParams: IndicatorParams
  placement: IndicatorPlacement
  bounds?: [number, number]
  guideLines?: number[]
  histogramOutput?: string
}

const item = (
  code: string,
  label: string,
  fullName: string,
  category: string,
  description: string,
  outputs: string[],
  defaultParams: IndicatorParams,
  placement: IndicatorPlacement = 'panel',
  extra: Partial<IndicatorDefinition> = {},
): IndicatorDefinition => ({
  value: code.toLowerCase(), code, label, fullName, category, description,
  outputs, defaultParams, placement, ...extra,
})

export const TECHNICAL_INDICATORS: IndicatorDefinition[] = [
  item('NONE', '无指标', '无技术指标', '基础', '专注观察价格走势与买卖信号。', [], {}, 'none'),
  item('VOLUME', '成交量', '成交量', '量价', '比较每根 K 线的成交活跃程度与涨跌方向。', ['VOL'], {}, 'panel'),
  item('MACD', 'MACD', '指数平滑异同移动平均线', '趋势', '用快慢均线差观察趋势方向与动能变化。', ['MACD_DIF', 'MACD_DEA', 'MACD_HIST'], { SHORT: 12, LONG: 26, M: 9 }, 'panel', { guideLines: [0], histogramOutput: 'MACD_HIST' }),
  item('KDJ', 'KDJ', '随机指标', '摆动', '结合近期高低价判断短期超买、超卖和拐点。', ['KDJ_K', 'KDJ_D', 'KDJ_J'], { N: 9, M1: 3, M2: 3 }, 'panel', { guideLines: [20, 80] }),
  item('RSI', 'RSI', '相对强弱指标', '摆动', '衡量一段时间内上涨与下跌力量的相对强弱。', ['RSI'], { N: 24 }, 'panel', { bounds: [0, 100], guideLines: [30, 70] }),
  item('BOLL', 'BOLL', '布林带', '通道', '用均线和标准差形成动态价格通道。', ['BOLL_UPPER', 'BOLL_MID', 'BOLL_LOWER'], { N: 20, P: 2 }, 'overlay'),
  item('BIAS', 'BIAS', '乖离率', '摆动', '衡量价格偏离不同周期均线的程度。', ['BIAS1', 'BIAS2', 'BIAS3'], { L1: 6, L2: 12, L3: 24 }, 'panel', { guideLines: [0] }),
  item('PSY', 'PSY', '心理线', '情绪', '统计近期上涨天数，观察市场情绪冷热。', ['PSY', 'PSY_MA'], { N: 12, M: 6 }, 'panel', { bounds: [0, 100], guideLines: [25, 75] }),
  item('TRIX', 'TRIX', '三重指数平滑平均线', '趋势', '通过三重平滑过滤短期噪声，识别中长期趋势。', ['TRIX', 'TRIX_MA'], { M1: 12, M2: 20 }, 'panel', { guideLines: [0] }),
  item('DPO', 'DPO', '区间震荡线', '摆动', '剥离长期趋势后观察价格周期性波动。', ['DPO', 'DPO_MA'], { M1: 20, M2: 10, M3: 6 }, 'panel', { guideLines: [0] }),
  item('MTM', 'MTM', '动量指标', '动量', '比较当前价格与过去价格，衡量涨跌速度。', ['MTM', 'MTM_MA'], { N: 12, M: 6 }, 'panel', { guideLines: [0] }),
  item('ROC', 'ROC', '变动率指标', '动量', '用价格变化率观察趋势加速、减速与反转。', ['ROC', 'ROC_MA'], { N: 12, M: 6 }, 'panel', { guideLines: [0] }),
  item('EXPMA', 'EXPMA', '指数平均数指标', '趋势', '用不同周期指数均线观察趋势和交叉。', ['EXPMA_12', 'EXPMA_50'], { N1: 12, N2: 50 }, 'overlay'),
  item('BBI', 'BBI', '多空指标', '趋势', '综合四条移动平均线，平滑判断多空方向。', ['BBI'], { M1: 3, M2: 6, M3: 12, M4: 20 }, 'overlay'),
  item('DFMA', 'DFMA', '平行线差指标', '趋势', '比较长短期均线差及其平滑线识别趋势。', ['DFMA_DIF', 'DFMA_DMA'], { N1: 10, N2: 50, M: 10 }, 'panel', { guideLines: [0] }),
  item('DMI', 'DMI', '动向指标', '趋势', '同时衡量多空方向与趋势强度。', ['DMI_PDI', 'DMI_MDI', 'DMI_ADX', 'DMI_ADXR'], { M1: 14, M2: 6 }, 'panel', { bounds: [0, 100] }),
  item('ATR', 'ATR', '平均真实波幅', '波动', '综合跳空与日内振幅衡量真实波动水平。', ['ATR'], { N: 20 }),
  item('WR', 'WR', '威廉指标', '摆动', '观察收盘价在近期高低区间中的相对位置。', ['WR1', 'WR2'], { N: 10, N1: 6 }, 'panel', { guideLines: [20, 80] }),
  item('CCI', 'CCI', '顺势指标', '摆动', '判断价格相对统计均值的偏离与极端状态。', ['CCI'], { N: 14 }, 'panel', { guideLines: [-100, 100] }),
  item('CR', 'CR', '价格动量指标', '情绪', '比较多空力量，观察市场买卖意愿变化。', ['CR'], { N: 20 }),
  item('KTN', 'KTN', '肯特纳通道', '通道', '以真实波幅构建动态通道，观察趋势与突破。', ['KTN_UPPER', 'KTN_MID', 'KTN_LOWER'], { N: 20, M: 10 }, 'overlay'),
  item('XSII', 'XSII', '薛斯通道 II', '通道', '以多条动态通道线观察中期价格运行范围。', ['XSII_TD1', 'XSII_TD2', 'XSII_TD3', 'XSII_TD4'], { N: 102, M: 7 }, 'overlay'),
  item('OBV', 'OBV', '能量潮', '量价', '按涨跌方向累计成交量，判断量价趋势是否一致。', ['OBV'], {}),
  item('VR', 'VR', '容量比率', '量价', '比较上涨日与下跌日成交量，观察市场活跃度。', ['VR'], { M1: 26 }),
  item('EMV', 'EMV', '简易波动指标', '量价', '结合价格移动与成交量衡量市场推动难易程度。', ['EMV', 'EMV_MA'], { N: 14, M: 9 }, 'panel', { guideLines: [0] }),
  item('MASS', 'MASS', '梅斯线', '波动', '用高低价波幅变化寻找趋势反转窗口。', ['MASS', 'MASS_MA'], { N1: 9, N2: 25, M: 6 }),
  item('MFI', 'MFI', '资金流量指标', '量价', '将价格与成交量结合，衡量资金流入流出强度。', ['MFI'], { N: 14 }, 'panel', { bounds: [0, 100], guideLines: [20, 80] }),
  item('BRAR', 'BRAR', '情绪指标', '情绪', '用开收高低价分别刻画人气与买卖意愿。', ['AR', 'BR'], { M1: 26 }),
  item('ASI', 'ASI', '振动升降指标', '趋势', '综合价格关系构造趋势累计线，过滤部分噪声。', ['ASI', 'ASI_MA'], { M1: 26, M2: 10 }, 'panel', { guideLines: [0] }),
  item('ZHUOYAO', '捉妖大师', '多周期涨幅共振', '特色', '比较多周期涨幅并观察趋势共振。', ['ZY_LONG', 'ZY_MID', 'ZY_SHORT', 'ZY_TREND'], { N1: 120, N2: 60, N3: 20, M: 10 }, 'panel', { guideLines: [0] }),
  item('BIAS_SIGNAL', '乖离信号', '三十日乖离率信号', '特色', '结合乖离率与长短信号线观察极端偏离。', ['BS_X', 'BS_SMA', 'BS_LMA'], { P: 10, M: 30 }, 'panel', { guideLines: [0] }),
  item('TAQ', 'TAQ', '唐奇安通道', '通道', '用近期最高价与最低价构建突破通道。', ['TAQ_UP', 'TAQ_MID', 'TAQ_DOWN'], { N: 20 }, 'overlay'),
  item('SAR', 'SAR', '抛物线转向', '趋势', '生成动态止损与趋势转向参考位。', ['SAR'], { AF_STEP: 0.02, AF_MAX: 0.2 }, 'overlay'),
  item('VWAP', 'VWAP', '成交量加权均价', '量价', '按成交量加权计算机构常用的动态成本基准。', ['VWAP'], { N: 20 }, 'overlay'),
  item('AROON', 'AROON', '阿隆指标', '趋势', '根据近期高低点出现时间识别趋势启动与强度。', ['AROON_UP', 'AROON_DOWN', 'AROON_OSC'], { N: 25 }, 'panel', { bounds: [-100, 100], guideLines: [0] }),
  item('FK', 'FK', '趋势快线', '特色', '用快线突破慢线斜率外推判断动量偏离。', ['FK'], {}, 'overlay'),
]

export const QUICK_INDICATORS = ['none', 'volume', 'macd', 'kdj', 'rsi', 'boll']
export const INDICATOR_CATEGORIES = ['全部', ...Array.from(new Set(TECHNICAL_INDICATORS.slice(2).map((entry) => entry.category)))]

export function getIndicatorDefinition(value: TechnicalIndicator): IndicatorDefinition {
  return TECHNICAL_INDICATORS.find((entry) => entry.value === value) ?? TECHNICAL_INDICATORS[0]
}

export function indicatorUsesPanel(value: TechnicalIndicator): boolean {
  return getIndicatorDefinition(value).placement === 'panel'
}

export async function calculateIndicatorRows(
  bars: Bar[],
  value: TechnicalIndicator,
  params: IndicatorParams,
): Promise<Array<Record<string, unknown>>> {
  const definition = getIndicatorDefinition(value)
  if (definition.code === 'NONE' || definition.code === 'VOLUME') return []
  const response = await computeIndicators(
    bars as unknown as Array<Record<string, unknown>>,
    [definition.code],
    { [definition.code]: params },
  )
  return response.data
}

const SERIES_COLORS = ['#56a8ff', '#f2c94c', '#c488ff', '#ff8a92', '#6ee0a5']

export function buildIndicatorSeries(
  value: TechnicalIndicator,
  bars: Bar[],
  rows: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const definition = getIndicatorDefinition(value)
  const xAxisIndex = definition.placement === 'panel' ? 1 : 0
  const yAxisIndex = definition.placement === 'panel' ? 1 : 0
  if (definition.code === 'NONE') return []
  if (definition.code === 'VOLUME') {
    return [{
      name: '成交量', type: 'bar', xAxisIndex, yAxisIndex,
      data: bars.map((bar) => bar.vol), barMaxWidth: 8,
      itemStyle: {
        color: (params: { dataIndex: number }) => bars[params.dataIndex].close >= bars[params.dataIndex].open
          ? 'rgba(255,94,104,.62)' : 'rgba(48,209,123,.62)',
        borderRadius: [2, 2, 0, 0],
      },
    }]
  }

  return definition.outputs.map((output, index) => {
    const data = rows.map((row) => {
      const numeric = Number(row[output])
      return Number.isFinite(numeric) ? numeric : null
    })
    const shared: Record<string, unknown> = {
      name: output.replace(`${definition.code}_`, ''),
      type: output === definition.histogramOutput ? 'bar' : 'line',
      xAxisIndex,
      yAxisIndex,
      data,
      animationDuration: 260,
    }
    if (output === definition.histogramOutput) {
      shared.barMaxWidth = 7
      shared.itemStyle = {
        color: (params: { value: number }) => params.value >= 0
          ? 'rgba(255,94,104,.62)' : 'rgba(48,209,123,.62)',
        borderRadius: 1,
      }
    } else {
      shared.symbol = definition.code === 'SAR' ? 'circle' : 'none'
      shared.symbolSize = definition.code === 'SAR' ? 4 : undefined
      shared.lineStyle = {
        color: SERIES_COLORS[index % SERIES_COLORS.length],
        width: definition.placement === 'overlay' ? 1.2 : 1.35,
        opacity: definition.placement === 'overlay' ? 0.88 : 1,
      }
      shared.itemStyle = { color: SERIES_COLORS[index % SERIES_COLORS.length] }
    }
    if (index === 0 && definition.guideLines?.length) {
      shared.markLine = {
        silent: true, symbol: 'none', label: { show: false },
        lineStyle: { color: 'rgba(255,255,255,.11)', type: 'dashed' },
        data: definition.guideLines.map((line) => ({ yAxis: line })),
      }
    }
    return shared
  })
}

export function percentageChange(bars: Bar[], index: number): number | null {
  if (index < 0 || index >= bars.length) return null
  const previousClose = index > 0 ? bars[index - 1].close : bars[index].open
  if (!Number.isFinite(previousClose) || previousClose === 0) return null
  return ((bars[index].close - previousClose) / previousClose) * 100
}

export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const absolute = Math.abs(value)
  if (absolute >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`
  if (absolute >= 10_000) return `${(value / 10_000).toFixed(2)}万`
  return value.toFixed(2)
}
