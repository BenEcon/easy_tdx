"""Preserve standard-event and structural baselines before the approved edits."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from easy_tdx.chanlun.divergence_signals import wave_events
from easy_tdx.chanlun.bi import find_bis
from easy_tdx.chanlun.fractal import find_fractals
from easy_tdx.chanlun.kline_merge import merge_klines
from tests.unit.test_wave_families import snapshot

def capture():
    result = {}
    for name in ('603936-min60-qfq-20261003', '603259-min30-qfq-20261003', '399006-min5-qfq-20261003'):
        bars, macd = snapshot(name)
        events = [asdict(e) for e in wave_events(bars, macd)]
        for event in events:
            event['evidence'].pop('rule_version', None)
            event['evidence'].pop('replacement_signal_index', None)
            event['evidence'].pop('replacement_detected_index', None)
        pens = find_bis(find_fractals(merge_klines(bars)))
        result[name] = {'standard': events, 'pens': [asdict(p) for p in pens]}
    paths = ['bi.py', 'fractal.py', 'kline_merge.py', 'xd.py', 'zs.py']
    result['structural_source'] = {p: hashlib.sha256(Path('src/easy_tdx/chanlun', p).read_bytes()).hexdigest()
                                   for p in paths if Path('src/easy_tdx/chanlun', p).exists()}
    return json.loads(json.dumps(result, default=str))

if __name__ == '__main__':
    path = Path(__file__).with_name('baseline.json')
    value = capture()
    if path.exists():
        assert value == json.loads(path.read_text()), 'Standard rules or structural baseline changed'
        print('Standard events, structural pens and source hashes unchanged across three frozen snapshots')
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding='utf-8')
        print('Baseline saved', path)
