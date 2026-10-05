"""Local-only real-market chart/replay fixture generator."""
import json
from pathlib import Path
from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.divergence_signals import special_wave_events, indicator_events, wave_events
from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from tests.unit.test_wave_families import snapshot

bars, macd = snapshot('603936-min15-qfq-20261004')
raw_rows = json.loads(Path('tests/fixtures/chanlun/603936-min15-qfq-20261004.json').read_text())['data'][-600:]
events = special_wave_events(bars, macd)
target = next(e for e in events if str(bars[e.signal_index].date) == '2026-09-15 09:45:00')
positions = [target.signal_index, target.signal_index+1, target.confirmed_index, target.confirmed_index+1, len(bars)]
stages = {}
for n in positions:
    prefix = bars[:n]
    m = {k:v[:n] for k,v in macd.items()}
    bcs = special_wave_events(prefix,m) + indicator_events(prefix,m) + wave_events(prefix,m) + wave_events(prefix,m,family='nonstandard')
    result = ChanlunResult(code='603936',frequency='15min',klines=prefix,macd=m,
        bis=find_bis(find_fractals(merge_klines(prefix))),bcs=bcs).to_dict()
    rows = raw_rows[:n]
    stages[n] = {'bars':rows,'result':result}
out = Path('web-ui/public/oct04-local-fixture.json')
out.write_text(json.dumps({'target':target.signal_index,'confirmed':target.confirmed_index,'stages':stages},ensure_ascii=False))
print(out,positions)
