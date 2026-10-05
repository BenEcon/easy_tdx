"""Inspect local strict-pair witnesses vs global pen selection, without patching it."""
from audit import load
from easy_tdx.chanlun.divergence_signals import special_wave_events
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from easy_tdx.chanlun.bi import find_bis, _can_form_bi
from easy_tdx.chanlun.config import ChanlunConfig
from easy_tdx.chanlun.anchors import extreme_index

cases=[('399006','MIN_5','2026-09-28 11:20'),('603936','MIN_15','2026-09-15 09:45'),
       ('002821','MIN_15','2026-09-14 10:00'),('002821','MIN_15','2026-09-18 09:45'),
       ('002821','MIN_30','2026-09-18 10:00')]
for code,period,date in cases:
    bars,m,_=load(code,period); cfg=ChanlunConfig()
    dt=lambda i: bars[i].date.strftime('%Y-%m-%d %H:%M') if i is not None else None
    at=next(i for i in range(len(bars)) if dt(i)==date)
    e=next(e for e in special_wave_events(bars,m) if e.signal_index==at)
    print('\nCASE',code,period,date,'invalidated',dt(e.invalidated_index),e.failure_reason)
    first_fx=None;pair=None
    for now in range(at+1,(e.invalidated_index or len(bars))):
        fxs=find_fractals(merge_klines(bars[:now+1]),cfg)
        start=next((fx for fx in fxs if extreme_index(fx)==at),None)
        if start is None: continue
        if first_fx is None:
            first_fx=now
            print('FIRST_FRACTAL',dt(now),'range',start.k.low,start.k.high,'merged',[(dt(b.index),b.low,b.high) for b in start.k.klines])
        end=next((fx for fx in fxs if _can_form_bi(start,fx,cfg)),None)
        if end is not None:
            pair=(now,start,end)
            break
    if pair:
        now,start,end=pair
        print('FIRST_LOCAL_PAIR',dt(now),'start',dt(extreme_index(start)),start.val,'end',dt(extreme_index(end)),end.val,
              'gap',end.klines[0].index-start.klines[2].index-1)
        bis=find_bis(find_fractals(merge_klines(bars[:now+1]),cfg),cfg)
        print('GLOBAL_NEARBY',[(dt(extreme_index(b.start)),b.start.val,dt(extreme_index(b.end)),b.end.val) for b in bis if extreme_index(b.end)>=at-10][-8:])
        fxs=find_fractals(merge_klines(bars[:now+1]),cfg)
        print('NEAR_FRACTALS',[(dt(extreme_index(f)),f.fx_type.value,f.val,f.k.index) for f in fxs if at-10<=extreme_index(f)<=extreme_index(end)])
    else:
        print('NO_LOCAL_PAIR_BEFORE_INVALIDATION')
        fxs=find_fractals(merge_klines(bars[:e.invalidated_index]),cfg)
        starts=[f for f in fxs if extreme_index(f)==at]
        if starts:
            s=starts[0]
            print('OPPOSITE_OPTIONS',[(dt(extreme_index(f)),f.val,f.klines[0].index-s.klines[2].index-1,_can_form_bi(s,f,cfg)) for f in fxs if f.k.index>s.k.index and f.fx_type!=s.fx_type])
