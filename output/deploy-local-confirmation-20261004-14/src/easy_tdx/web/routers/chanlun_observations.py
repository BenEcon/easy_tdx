"""Common-cutoff multi-frequency observations on supplied frozen snapshots."""
from datetime import datetime
from typing import Literal

import pandas as pd
from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from easy_tdx.chanlun.observations import observe
from easy_tdx.web.bar_snapshot import period_end
from easy_tdx.web.routers.chanlun_replay import ReplaySeries

router = APIRouter(tags=['chanlun'])


class StudySeries(ReplaySeries):
    category: Literal['MIN_1', 'MIN_5', 'MIN_15', 'MIN_30', 'MIN_60', 'MIN_120', 'DAY', 'WEEK', 'MONTH']


class StudyRequest(BaseModel):
    as_of: datetime
    series: list[StudySeries] = Field(min_length=1, max_length=9)
    volume_multiple: float = Field(default=2, ge=1, le=10)
    squeeze_quantile: float = Field(default=.2, gt=0, lt=1)

    @model_validator(mode='after')
    def valid_snapshot(self):
        if self.as_of.tzinfo is not None:
            raise ValueError('共同截止时刻使用交易所本地时间')
        if len({s.code for s in self.series}) != 1 or len({s.category for s in self.series}) != len(self.series):
            raise ValueError('多周期须为同一标的，周期不可重复')
        return self


@router.post('/chanlun/observations')
def observations(req: StudyRequest):
    rows = []
    for source in req.series:
        # Never use the final OHLC of a higher-period candle spanning the cutoff.
        eligible = [bar for bar in source.bars if period_end(bar.datetime, source.category) <= req.as_of]
        if not eligible:
            rows.append({'category': source.category, 'error': '共同截止时刻前无完整 K 线；未使用跨越截止点的整根行情'})
            continue
        frame = pd.DataFrame([bar.model_dump() for bar in eligible])
        row = observe(frame, source.category, volume_multiple=req.volume_multiple,
                      squeeze_quantile=req.squeeze_quantile)
        row['excluded_bars'] = len(source.bars) - len(eligible)
        rows.append(row)
    conflicts = []
    rank = {'MIN_1': 1, 'MIN_5': 5, 'MIN_15': 15, 'MIN_30': 30, 'MIN_60': 60, 'MIN_120': 120,
            'DAY': 240, 'WEEK': 1200, 'MONTH': 4800}
    ordered = sorted((r for r in rows if 'error' not in r), key=lambda r: rank[r['category']])
    names = {'DAY': '日线', 'WEEK': '周线', 'MONTH': '月线'}
    def label(category):
        return names.get(category, category.removeprefix('MIN_') + ' 分钟')
    for small, large in zip(ordered, ordered[1:]):
        # Only report a divergence on the last completed bar or confirmed there;
        # old historical markers must not trigger a new current conflict.
        tops = [d for d in small['divergences'] if d['direction'] == 'up' and
                small['last_date'] in (d['date'], d['confirmed_date'])]
        if tops and large['above_ma10'] and large['pairs']['macd']['fast'] > large['pairs']['macd']['slow']:
            conflicts.append(f"{label(small['category'])} 出现局部顶背离，{label(large['category'])} 仍位于 MA10 上方且 DIF 高于 DEA；不能直接等同于大周期反转")
        bottoms = [d for d in small['divergences'] if d['direction'] == 'down' and
                   small['last_date'] in (d['date'], d['confirmed_date'])]
        if (bottoms and large['above_ma10'] is False and large['price'] < large['ma10']
                and large['pairs']['macd']['fast'] < large['pairs']['macd']['slow']):
            conflicts.append(f"{label(small['category'])} 出现局部底背离，{label(large['category'])} 仍位于 MA10 下方且 DIF 低于 DEA；不能直接等同于大周期反转")
    return {'as_of': req.as_of.isoformat(sep=' '), 'rows': rows, 'conflicts': conflicts,
            'rule_version': 'multi-period-observation-v1', 'eligible_for_trading': False,
            'parameters': {'macd': [12, 26, 9], 'boll': [20, 2], 'volume_multiple': req.volume_multiple,
                           'squeeze_quantile': req.squeeze_quantile},
            'policy': '仅使用共同截止点前完整 K 线；结构层级不等于图表周期；不按周期多数投票'}
