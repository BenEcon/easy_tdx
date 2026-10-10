"""Verify legacy and untouched families against the actual pre-change source."""
import tarfile
import types
from dataclasses import asdict
from pathlib import Path
from easy_tdx.chanlun import divergence_signals as current
from tests.unit.test_wave_families import snapshot

root = Path(__file__).resolve().parent
with tarfile.open(root/'prechange-source.tar.gz') as archive:
    before = types.ModuleType('prechange_divergence')
    exec(compile(archive.extractfile('src/easy_tdx/chanlun/divergence_signals.py').read(), 'prechange_divergence.py', 'exec'), before.__dict__)
    for name in ('bi.py','fractal.py','kline_merge.py','xd.py','zs.py'):
        assert archive.extractfile('src/easy_tdx/chanlun/'+name).read() == Path('src/easy_tdx/chanlun',name).read_bytes(), name
for name in ('603936-min60-qfq-20261003','603259-min30-qfq-20261003','399006-min5-qfq-20261003'):
    bars, macd = snapshot(name)
    for family in ('standard','nonstandard','special','double'):
        if family in ('standard','nonstandard'):
            old = before.wave_events(bars,macd,family=family)
            new = current.wave_events(bars,macd,family=family,legacy_standard=True)
        else:
            func = 'special_wave_events' if family == 'special' else 'indicator_events'
            old, new = (getattr(module,func)(bars,macd) for module in (before,current))
        assert [asdict(e) for e in old] == [asdict(e) for e in new], (name,family)
    print('PASS legacy standard, nonstandard, special and dual:',name)
print('PASS strict pen, fractal, inclusion, segment and centre sources unchanged')
