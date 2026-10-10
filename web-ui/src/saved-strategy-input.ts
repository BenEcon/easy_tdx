import { navigationPeriods, navigationTarget } from './research-navigation.ts'
import { detectMarket } from './market.ts'
import type { AdjustMode, Category, ExecutionMode, SavedStrategy } from './types'

export interface SavedInputDefaults {
  category:Category;adjust:AdjustMode;startDate:string;endDate:string;cash:number;
  commission:number;minCommission:number;stampTax:number;slippage:number;execution:ExecutionMode
}
export function savedStrategyRequestId(query:Record<string,unknown>): string {
  if(typeof query.savedStrategyId!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(query.savedStrategyId)) throw Error('策略载入链接缺少有效 ID')
  if(Object.keys(query).some(key=>key!=='savedStrategyId'))throw Error('策略载入不能混用自动运行、雷达或其他参数')
  return query.savedStrategyId
}
function date(value:unknown):string {
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value)||!Number.isFinite(Date.parse(value))||new Date(value).toISOString().slice(0,10)!==value)throw Error('保存的日期无效')
  return value
}
/** Restore recorded settings, never infer a market from an explicit conflicting prefix.
 * Missing legacy fields are disclosed and use the supplied visible form defaults.
 */
export function savedStrategyInput(record:SavedStrategy, defaults:SavedInputDefaults, strategies:ReadonlyArray<string>) {
  if(record.kind!=='single')throw Error('该记录不是单标的策略，请在对应组合页面载入')
  if(!strategies.includes(record.strategy))throw Error('保存的策略在当前版本不可用，未替换为其他策略')
  const warnings:string[]=[]
  const ctx=record.context??{}, trade=record.trade_config??{}
  const symbol=typeof ctx.symbol==='string'?ctx.symbol:''
  const match=/^(?:(SH|SZ|BJ):)?(\d{6})$/.exec(symbol)
  if(!match)throw Error('保存的策略缺少有效标的代码')
  const code=match[2]!,market=match[1]??detectMarket(code)
  if(!match[1])warnings.push('旧记录未保存市场，按普通证券代码规则识别；请核对')
  const identity=navigationTarget({code,market})
  if(!identity.target||!['stock','fund'].includes(identity.target.kind))throw Error('保存的标的市场或类型与个股回测不匹配')
  const get=(source:Record<string,unknown>,key:string,fallback:unknown,label:string)=>{
    if(source[key]===undefined){warnings.push(`未保存${label}，采用本页设置`);return fallback}
    return source[key]
  }
  const category=get(ctx,'category',defaults.category,'周期') as Category
  const adjust=get(ctx,'adjust',defaults.adjust,'复权方式') as AdjustMode
  if(!navigationPeriods.some(p=>p.value===category))throw Error('保存的周期在本页不支持')
  if(!['QFQ','HFQ','NONE'].includes(adjust))throw Error('保存的复权方式无效')
  const startDate=date(get(ctx,'start_date',defaults.startDate,'开始日期'))
  const endDate=date(get(ctx,'end_date',defaults.endDate,'结束日期'))
  if(startDate>endDate)throw Error('保存的开始日期晚于结束日期')
  const number=(key:string,fallback:number,label:string,max=Infinity,positive=false)=>{
    const value=get(trade,key,fallback,label)
    if(typeof value!=='number'||!Number.isFinite(value)||value<0||value>max||(positive&&value===0))throw Error(`保存的${label}无效`)
    return value
  }
  const cash=number('cash',defaults.cash,'初始资金',Infinity,true)
  const commission=number('commission',defaults.commission,'佣金率',.01)
  const minCommission=number('min_commission',defaults.minCommission,'最低佣金')
  const stampTax=number('stamp_tax',defaults.stampTax,'印花税率',.01)
  const slippage=number('slippage',defaults.slippage,'滑点',.05)
  const execution=get(trade,'execution',defaults.execution,'成交模式') as ExecutionMode
  if(!['next_open','next_close'].includes(execution))throw Error('保存的成交模式无效')
  if(!record.params||Array.isArray(record.params)||typeof record.params!=='object'||Object.values(record.params).some(value=>!['number','string','boolean'].includes(typeof value)||(typeof value==='number'&&!Number.isFinite(value))))throw Error('保存的策略参数无效')
  return{code,market,category,adjust,startDate,endDate,cash,commission,minCommission,stampTax,slippage,execution,strategy:record.strategy,params:{...record.params},warnings}
}

/** Portfolio uses the same execution contract, but every member identity must be valid. */
export function savedPortfolioInput(record:SavedStrategy,defaults:SavedInputDefaults,strategies:ReadonlyArray<string>) {
  if(record.kind!=='portfolio')throw Error('该记录不是多标的组合策略')
  const stocks=record.context?.stocks
  if(!Array.isArray(stocks)||stocks.length<1||stocks.length>20)throw Error('组合必须保存 1 至 20 个标的')
  const inputs=stocks.map(symbol=>savedStrategyInput({...record,kind:'single',context:{...record.context,symbol}},defaults,strategies))
  const symbols=inputs.map(input=>`${input.market}:${input.code}`)
  if(new Set(symbols).size!==symbols.length)throw Error('组合保存了重复标的，请先核对记录')
  const {code:_,market:__,...common}=inputs[0]!
  return {...common,stocks:symbols,warnings:[...new Set(inputs.flatMap(input=>input.warnings))]}
}
