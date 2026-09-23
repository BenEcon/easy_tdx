"""Regression coverage for causal divergence semantics, independent of data vendor."""
import unittest
from datetime import datetime, timedelta

from easy_tdx.chanlun.divergence_signals import indicator_events, segment_evidence, wave_events
from easy_tdx.chanlun.types import Kline


def bars(lows):
    return [Kline(i, datetime(2026, 1, 1) + timedelta(days=i), v + .5, v + .5,
                  v + 1, v, 100) for i, v in enumerate(lows)]


class DivergenceSignalsTest(unittest.TestCase):
    def test_wave_confirmation_on_colour_change_not_low_date(self):
        ks = bars([25, 24, 20, 22, 23, 19, 19.5, 21])
        m = {"dif": [.1, -2, -2, -1, -.5, -1.5, -1.4, -1.3],
             "dea": [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1],
             "hist": [.2, -2, -1, .3, .2, -.5, -.2, .1]}
        event = wave_events(ks, m)[0]
        self.assertEqual(event.signal_index, 5)
        self.assertEqual(event.detected_index, 6)
        self.assertEqual(event.confirmed_index, 7)
        self.assertAlmostEqual(event.evidence['area_ratio'], .7 / 3)
        prefix = wave_events(ks[:7], {k: v[:7] for k, v in m.items()})
        self.assertEqual(prefix[0].status, 'candidate')
        self.assertIsNone(prefix[0].confirmed_index)
        # No signal from an incomplete, still-expanding green wave.
        self.assertFalse(wave_events(ks[:6], {k: v[:6] for k, v in m.items()}))

    def test_wave_can_confirm_without_prior_candidate_and_skips_truncated_a(self):
        ks = bars([25, 24, 20, 22, 23, 19, 18, 21])
        m = {"dif": [.1, -2, -2, -1, -.5, -1.5, -1.4, -1.3],
             "dea": [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1],
             "hist": [.2, -2, -1, .3, .2, -.1, -.2, .1]}
        event = wave_events(ks, m)[0]
        self.assertEqual((event.signal_index, event.detected_index, event.confirmed_index), (6, 7, 7))
        self.assertFalse(wave_events(ks[1:], {k: v[1:] for k, v in m.items()}))

    def test_wave_invalidates_candidate_if_area_grows(self):
        ks = bars([25, 24, 20, 22, 23, 19, 19.5, 18, 21])
        m = {"dif": [.1, -2, -2, -1, -.5, -1.5, -1.4, -1.3, -1.2],
             "dea": [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1, -1],
             "hist": [.2, -2, -1, .3, .2, -.5, -.2, -4, .1]}
        events = wave_events(ks, m)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, 'superseded')
        self.assertIsNone(events[0].confirmed_index)

    def test_confirmed_wave_survives_prefix_replay(self):
        ks = bars([25, 24, 20, 22, 23, 19, 19.5, 21, 20, 18, 22])
        m = {"dif": [.1, -2, -2, -1, -.5, -1.5, -1.4, -1.3, -1.2, -1.1, -1],
             "dea": [.1, -1.8, -1.7, -1.2, -.9, -1.3, -1.2, -1.1, -1, -.9, -.8],
             "hist": [.2, -2, -1, .3, .2, -.5, -.2, .1, .2, -.1, .1]}
        full = wave_events(ks, m)
        for n in range(1, len(ks) + 1):
            prefix = wave_events(ks[:n], {k: v[:n] for k, v in m.items()})
            expected = [(e.signal_index, e.confirmed_index, e.evidence) for e in full
                        if e.confirmed_index is not None and e.confirmed_index < n]
            actual = [(e.signal_index, e.confirmed_index, e.evidence) for e in prefix
                      if e.status == 'confirmed']
            self.assertEqual(expected, actual)

    def test_candidate_confirmation_and_supersession(self):
        ks = bars([22, 20, 21, 19.21, 20, 19.18, 19.15, 20])
        m = {"dif": [-2, -2, -1.9, -1.5, -1.4, -1.3, -1.2, -1.1],
             "dea": [-1.8, -1.8, -1.7, -1.4, -1.3, -1.2, -1.1, -1],
             "hist": [.1] * 8}
        events = indicator_events(ks, m)
        low = {e.signal_index: e for e in events if e.direction == "down"}
        self.assertEqual(low[3].confirmed_index, 4)
        self.assertEqual(low[5].status, "superseded")
        self.assertIsNone(low[5].confirmed_index)
        self.assertEqual(low[6].confirmed_index, 7)
        self.assertEqual(low[6].reference_index, 3)
        # Positive histogram is allowed; a price pivot cannot confirm itself.
        prefix = indicator_events(ks[:4], {k: v[:4] for k, v in m.items()})
        self.assertEqual(prefix[-1].status, "candidate")
        self.assertIsNone(prefix[-1].confirmed_index)

    def test_no_new_low_and_dea_not_improving(self):
        ks = bars([22, 20.49, 22, 20.58, 22, 19.71, 22])
        m = {"dif": [-2, -1.569, -1.4, -1.25, -1.2, -1.3228, -1],
             "dea": [-1.5, -1.2447, -1.2, -1.2992, -1.2, -1.2928, -1],
             "hist": [-.2] * 7}
        events = indicator_events(ks, m)
        self.assertFalse(any(e.signal_index == 3 for e in events))
        # Isolate the original reference rather than silently comparing to a higher low.
        ks2 = bars([22, 20.49, 22, 19.71, 22])
        m2 = {k: [v[i] for i in [0, 1, 2, 5, 6]] for k, v in m.items()}
        self.assertFalse(indicator_events(ks2, m2))

    def test_segment_troughs_not_endpoint_lines(self):
        ks = bars([24, 21, 20, 22, 23, 21, 19])
        m = {"dif": [-1, -2, -1.5, -.5, -.4, -1.3, -1.4],
             "dea": [-1, -1.8, -1.2, -.8, -.5, -1.4, -1.3],
             "hist": [-1, -2, -1, .2, .3, -.2, -.1]}
        evidence = segment_evidence(ks, m, (0, 2), (4, 6), "down")
        self.assertIsNotNone(evidence)
        self.assertAlmostEqual(evidence["c_area"], .3)
        m["hist"][5] = -5
        self.assertIsNone(segment_evidence(ks, m, (0, 2), (4, 6), "down"))

    def test_mirror_top(self):
        ks = bars([20, 22, 21, 23, 22])
        m = {"dif": [2, 2, 1.9, 1.5, 1.4], "dea": [1.8, 1.8, 1.7, 1.4, 1.3],
             "hist": [-.1] * 5}
        top = [e for e in indicator_events(ks, m) if e.direction == "up"]
        self.assertEqual(top[0].signal_index, 3)
        self.assertEqual(top[0].confirmed_index, 4)


if __name__ == '__main__':
    unittest.main()
