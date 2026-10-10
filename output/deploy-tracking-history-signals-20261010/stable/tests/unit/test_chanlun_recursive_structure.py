"""Higher centre lifecycles retain real child identity and causal admission."""

from copy import deepcopy
from datetime import datetime, timedelta
from importlib import import_module

import pytest

from easy_tdx.chanlun.analyser import ChanlunResult
from easy_tdx.chanlun.engineering_trends import engineering_trend_hierarchy
from easy_tdx.chanlun.recursive_structure import recursive_structure_layer
from easy_tdx.chanlun.types import Kline
from tests.unit.test_chanlun_engineering_trends import nested_prices
from tests.unit.test_chanlun_structure import segments, signal_fixture


def adapters(prices, offset=0):
    """Isolated lifecycle adapters, not claims of actual trend completion."""
    lines = segments(prices)
    for line in lines:
        line.index += offset
    records = {
        line.index: {
            "id": f"trend:L1:{9 * line.index}:{9 * line.index + 8}",
            "source_segment_indices": list(range(9 * line.index, 9 * line.index + 9)),
        }
        for line in lines
    }
    return lines, records


@pytest.mark.parametrize("offset", [0, 37])
def test_formation_departure_and_return_keep_actual_child_ids(offset):
    lines, records = adapters([14, 10, 12, 8, 20, 16, 22, 18], offset)

    def run(n):
        return recursive_structure_layer([lines[:n]], records, 1)["chains"][0]

    assert not run(2)["centres"]
    formed = run(3)["centres"][0]
    assert formed["state"] == "formed" and formed["formed_index"] == 110
    pending = run(4)["centres"][0]
    assert pending["state"] == "departed"
    assert pending["departure_id"] == records[offset + 3]["id"]
    assert pending["source_unit_ids"] == [records[offset + i]["id"] for i in range(3)]
    exited = run(5)["centres"][0]
    assert exited["return_id"] == records[offset + 4]["id"]
    assert exited["exited_index"] == 120
    assert exited["source_unit_ids"] == formed["source_unit_ids"]
    assert not exited["natural_type_complete"] and not exited["eligible_for_trend_recursion"]
    final = run(len(lines))
    assert final["centres"][0] == exited
    assert final["centres"][1]["relation_history"][0]["previous_centre_id"] == exited["id"]
    assert all(
        i not in exited["source_segment_indices"]
        for i in records[offset + 4]["source_segment_indices"]
    )


def test_failed_return_admission_and_nine_unit_extension_use_actual_known_time():
    lines, records = adapters([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4])
    before = recursive_structure_layer([lines[:9]], records, 1)["chains"][0]
    assert not before["extension_proofs"]
    assert records[8]["id"] not in before["centres"][0]["source_unit_ids"]
    at = recursive_structure_layer([lines], records, 1)["chains"][0]
    proof = at["extension_proofs"][0]
    assert proof["relative_depth"] == 2 and proof["input_level"] == 1
    assert proof["known_index"] == lines[9].confirmed_index
    assert proof["source_unit_ids"] == [records[i]["id"] for i in range(9)]
    assert proof["source_segment_indices"] == list(range(81))
    assert proof["member_admissions"][-1]["witness_id"] == records[9]["id"]
    assert proof["member_admissions"][-1]["unit_confirmed_index"] == lines[8].confirmed_index
    assert proof["member_admissions"][-1]["admitted_index"] == lines[9].confirmed_index
    assert [s for child in proof["children"] for s in child["source_segment_indices"]] == list(
        range(81)
    )
    assert not proof["natural_type_complete"] and not proof["eligible_for_trend_recursion"]


def test_disconnected_chains_cannot_form_a_centre_or_upgrade():
    lines, records = adapters([14, 10, 12, 8, 20, 16, 22, 18])
    layer = recursive_structure_layer([lines[:2], lines[3:5]], records, 1)
    assert len(layer["chains"]) == 2
    assert layer["chains"][0]["id"] != layer["chains"][1]["id"]
    assert all(not c["centres"] and not c["extension_proofs"] for c in layer["chains"])


def test_history_proofs_and_snapshots_are_independent():
    lines, records = adapters([0, 10, 2, 8, 2, 8, 2, 8, 2, 12, 4])
    original = deepcopy((lines, records))
    final = recursive_structure_layer([lines], records, 1)
    for n in range(1, len(lines) + 1):
        prefix = recursive_structure_layer([lines[:n]], records, 1)["chains"][0]
        known = lines[n - 1].confirmed_index
        assert prefix["extension_proofs"] == [
            p for p in final["chains"][0]["extension_proofs"] if p["known_index"] <= known
        ]
        for centre in prefix["centres"]:
            last = next(c for c in final["chains"][0]["centres"] if c["id"] == centre["id"])
            assert centre["transitions"] == [
                t for t in last["transitions"] if t["known_index"] <= known
            ]
    final["chains"][0]["centres"][0]["source_unit_ids"].clear()
    final["chains"][0]["extension_proofs"][0]["children"].clear()
    assert (lines, records) == original
    again = recursive_structure_layer([lines], records, 1)
    assert again["chains"][0]["extension_proofs"][0]["children"]


def nested_fixture():
    prices = nested_prices(2)
    items, _, macd = signal_fixture(prices)
    bars = [
        Kline(
            i,
            datetime(2026, 1, 1) + timedelta(days=i),
            prices[min(i // 4, len(prices) - 1)],
            prices[min(i // 4, len(prices) - 1)],
            prices[min(i // 4, len(prices) - 1)],
            prices[min(i // 4, len(prices) - 1)],
            0,
        )
        for i in range(101 + 5 * len(items))
    ]
    return items, bars, macd


def test_real_recursive_path_keeps_centre_before_any_t2_completion(monkeypatch):
    module = import_module("easy_tdx.chanlun.engineering_trends")
    monkeypatch.setattr(module, "segment_evidence", lambda *args: {"area_ratio": 0.5})
    items, bars, macd = nested_fixture()
    # First three completed T1 inputs form an upper centre, but not a T2 trend.
    count = items[27].confirmed_index + 1
    before = engineering_trend_hierarchy(items, bars[: count - 1], macd)
    assert not before["structure_layers"][0]["chains"][0]["centres"]
    at = engineering_trend_hierarchy(items, bars[:count], macd)
    assert at["highest_completed_trend_level"] == 1
    centre = at["structure_layers"][0]["chains"][0]["centres"][0]
    assert len(centre["source_unit_ids"]) == 3
    assert centre["source_segment_indices"] == list(range(27))
    assert centre["formed_index"] == count - 1
    assert centre["end_index"] < centre["formed_index"]
    final = engineering_trend_hierarchy(items, bars, macd)
    assert final["highest_completed_trend_level"] == 2
    assert [layer["input_level"] for layer in final["structure_layers"]] == [1, 2]
    assert not final["structure_layers"][1]["chains"][0]["centres"]  # only one T2
    lookup = {t["id"]: t for t in final["levels"][0]["types"]}
    for c in final["structure_layers"][0]["chains"][0]["centres"]:
        assert [
            s for unit in c["source_unit_ids"] for s in lookup[unit]["source_segment_indices"]
        ] == c["source_segment_indices"]


def test_recursive_lifecycle_serializes_actual_dates_without_trading_signals(monkeypatch):
    module = import_module("easy_tdx.chanlun.engineering_trends")
    monkeypatch.setattr(module, "segment_evidence", lambda *args: {"area_ratio": 0.5})
    items, bars, macd = nested_fixture()
    result = ChanlunResult(xds=items, klines=bars, macd=macd)
    data = result.to_dict()
    chain = data["engineering_trend_hierarchy"]["structure_layers"][0]["chains"][0]
    centre = chain["centres"][0]
    assert centre["formed_date"] == result._fmt_dt(bars[centre["formed_index"]].date)
    assert centre["transitions"][0]["known_date"] == centre["formed_date"]
    assert centre["member_admissions"][0]["admitted_date"] == centre["formed_date"]
    assert not data["mmds"] and not data["bcs"]
    assert not data["structure_metadata"]["recursive_levels_ready"]
