"""Every fixed-chain start/end attempt has an actual detector outcome."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from easy_tdx.chanlun.divergence_signals import segment_evidence
from easy_tdx.chanlun.engineering_consolidations import consolidation_candidates
from easy_tdx.chanlun.engineering_trends import _candidates
from easy_tdx.chanlun.exhaustive_recursion import exhaustive_leaf
from easy_tdx.chanlun.structure import confirmed_segment_prefix
from easy_tdx.web.routers.chanlun_replay import CandidateAuditRequest, replay_candidate_audit
from tests.unit.test_chanlun_released_recursion import release_fixture
from tests.unit.test_divergence_signals import bars


def test_missing_reverse_is_pending_until_actual_next_confirmation():
    items, ks, macd = release_fixture()
    before = exhaustive_leaf(items[:5], ks, macd, trace=True)["audit"]["attempts"]
    pending = [r for r in before if r["outcome"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["reason"] == "reverse_not_yet_confirmed"
    assert all(g["passed"] for g in pending[0]["macd_checks"])
    after = exhaustive_leaf(items[:6], ks, macd, trace=True)["audit"]["attempts"]
    match = next(
        r
        for r in after
        if r["kind"] == pending[0]["kind"]
        and r["start_unit_index"] == pending[0]["start_unit_index"]
        and r["end_unit_index"] == pending[0]["end_unit_index"]
    )
    assert match["outcome"] == "candidate" and match["confirmed_index"] == items[5].confirmed_index
    assert pending[0]["outcome"] == "pending"


def test_missing_series_and_nonfinite_values_do_not_invent_downstream_checks():
    items, ks, macd = release_fixture()
    trace = exhaustive_leaf(items, ks, {}, trace=True)["audit"]["attempts"]
    assert len(trace) == len(items) * (len(items) + 1)
    assert all(r["reason"] == "macd_series_missing" and not r["macd_checks"] for r in trace)
    macd["dea"][1] = float("nan")
    checks = []
    assert segment_evidence(ks, macd, (0, 4), (16, 20), "down", audit=checks) is None
    assert len(checks) == 4
    assert next(r for r in checks if r["gate"] == "dea_finite_coverage")["passed"] is False
    json.dumps(checks, allow_nan=False)


def test_noninternal_detector_traces_its_final_protected_source_rejection():
    inputs = release_fixture()
    trace = []
    actual = _candidates(*inputs, trace=trace)
    assert actual == _candidates(*inputs)
    assert len(actual) == sum(r["outcome"] == "candidate" for r in trace)


def test_omitting_a_middle_candidate_explains_all_cross_gap_windows():
    inputs = release_fixture()
    path = []
    while path is not None:
        leaf = exhaustive_leaf(*inputs, path, trace=True)
        if leaf["audit"]["chain_boundaries"]:
            for boundary in leaf["audit"]["chain_boundaries"]:
                assert boundary["effect"] == "all_cross_boundary_windows_not_evaluated"
                assert boundary["reason"] in ("unresolved_source_gap", "source_chain_disconnected")
            return
        path = leaf["next_path"]
    pytest.fail("fixture must exercise a recursive chain gap")


@pytest.mark.parametrize("mirror", [False, True])
def test_every_window_traced_and_candidate_outputs_identical(mirror):
    items, rows, macd = release_fixture(mirror)
    for kind in ("trend", "consolidation"):
        trace = []

        def detect(**kwargs):
            return (
                _candidates(items, rows, macd, internal=True, **kwargs)
                if kind == "trend"
                else consolidation_candidates(items, rows, macd, **kwargs)
            )

        plain, traced = detect(), detect(trace=trace)
        assert plain == traced
        expected = {(a.index, b.index) for i, a in enumerate(items) for b in items[i:]}
        actual = {(r["start_unit_index"], r["end_unit_index"]) for r in trace}
        assert actual == expected and len(trace) == len(expected)
        found = [r for r in trace if r["outcome"] == "candidate"]
        assert len(found) == len(plain)
        assert all(r["outcome"] != "not_evaluated" for r in trace)
        assert all(r["reason"] is not None for r in trace if r["outcome"] != "candidate")


def test_macd_audit_evaluates_independent_failures_without_claiming_pass():
    ks = bars([10, 9, 11, 12, 13, 10, 11])
    macd = {"dif": [-2] * 7, "dea": [-1] * 7, "hist": [-1, -1, 1, 1, -4, -4, 1]}
    checks = []
    assert segment_evidence(ks, macd, (0, 1), (4, 5), "down", audit=checks) is None
    failed = {row["gate"] for row in checks if not row["passed"]}
    assert {
        "strict_price_extreme",
        "shrinking_same_colour_area",
        "dif_extreme_and_zero_axis",
        "dea_extreme_and_zero_axis",
    } <= failed
    assert len(checks) == 10
    invalid = []
    assert segment_evidence(ks, macd, (4, 5), (0, 1), "down", audit=invalid) is None
    assert len(invalid) == 1 and not invalid[0]["passed"]


def test_source_rejection_records_actual_first_failure():
    items, ks, _ = release_fixture()
    bad = deepcopy(items)
    bad[2].confirmed_index = len(ks)
    trace = []
    assert len(confirmed_segment_prefix(bad, len(ks), audit=trace)) == 2
    assert trace[0]["position"] == 2
    assert trace[0]["reason"] == "confirmation_unavailable"


def test_real_market_audit_covers_all_six_base_segments_and_pagination():
    path = Path(__file__).parents[1] / "fixtures/chanlun/600699-qfq-20260929.json"
    data = json.loads(path.read_text())
    request = CandidateAuditRequest(code="600699", bars=data["bars"], visible_count=800, limit=10)
    rows, offset = [], 0
    while offset is not None:
        response = replay_candidate_audit(request.model_copy(update={"offset": offset}))
        rows.extend(response["attempts"])
        offset = response["next_offset"]
    assert response["input"]["accepted_segment_count"] == 6
    assert len(rows) == response["total_attempts"] == 42
    assert all(r["level"] == 1 and r["outcome"] != "candidate" for r in rows)
