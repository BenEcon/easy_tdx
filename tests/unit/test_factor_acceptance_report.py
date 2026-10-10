"""A checklist cannot turn absent, skipped or conflicting evidence into passes."""

from scripts.factor_acceptance_report import checklist, gate, read_evidence


def test_missing_evidence_is_incomplete_for_every_factor():
    rows = checklist({})
    assert len(rows) == 396
    assert all(r["kernel_evidence"] == "incomplete" for r in rows)
    assert all(r["full_goal_acceptance"] == "not_established" for r in rows)
    assert len([r for r in rows if r["library"] == "qlib_alpha158"]) == 158
    assert len([r for r in rows if r["library"] == "gtja191"]) == 191
    assert len([r for r in rows if r["library"] == "alpha101"]) == 28


def test_partial_and_skipped_cases_cannot_pass_the_gate():
    evidence = {("m", "a"): "passed", ("m", "b"): "skipped"}
    assert gate(evidence, "x", "m", ["a"])["status"] == "passed"
    for names in ([], ["a", "b"], ["a", "c"]):
        assert gate(evidence, "x", "m", names)["status"] == "incomplete"


def test_self_recursive_factor_requires_numerical_range_and_archive_evidence():
    name = "gtja191_143"
    row = next(r for r in checklist({}) if r["name"] == name)
    cases = [c for check in row["checks"] for c in check["cases"]]
    evidence = {tuple(c["id"].split("::")): "passed" for c in cases}
    assert (
        next(r for r in checklist(evidence) if r["name"] == name)["kernel_evidence"]
        == "passed_listed_checks"
    )
    for case in (
        "test_self_underflow_overflow_preserves_state_and_decimal_ties",
        "test_self_research_archive_readonly_recompute",
    ):
        partial = dict(evidence)
        del partial[("tests.unit.test_gtja191_self_recursion", case)]
        assert (
            next(r for r in checklist(partial) if r["name"] == name)["kernel_evidence"]
            == "incomplete"
        )


def test_gtja006_requires_decimal_tie_regression_evidence():
    row = next(r for r in checklist({}) if r["name"] == "gtja191_006")
    cases = [c for check in row["checks"] for c in check["cases"]]
    evidence = {tuple(c["id"].split("::")): "passed" for c in cases}
    key = ("tests.unit.test_gtja191", "test_alpha006_decimal_equal_weighted_prices_remain_tied")
    del evidence[key]
    missing = next(r for r in checklist(evidence) if r["name"] == "gtja191_006")
    assert missing["kernel_evidence"] == "incomplete"


def test_conflicting_junit_keeps_failure_and_skip(tmp_path):
    paths = [tmp_path / "first.xml", tmp_path / "second.xml"]
    paths[0].write_text(
        '<testsuites><testsuite><testcase classname="m" name="a"><failure/></testcase>'
        '<testcase classname="m" name="b"><skipped/></testcase></testsuite></testsuites>'
    )
    paths[1].write_text(
        '<testsuites><testsuite><testcase classname="m" name="a"/>'
        '<testcase classname="m" name="b"/></testsuite></testsuites>'
    )
    for order in (paths, paths[::-1]):
        assert read_evidence(order) == {("m", "a"): "failed", ("m", "b"): "skipped"}


def test_adjusted_vwap_cannot_gain_coverage_from_unsupported_fixtures():
    rows = {row["name"]: row for row in checklist({})}
    cases = rows["alpha158_vwap0"]["checks"][-1]["cases"]
    assert len(cases) == 4 and all("-NONE.json]" in case["id"] for case in cases)
    cases = rows["alpha158_ma5"]["checks"][-2]["cases"]
    assert len(cases) == 12


def test_multistage_requires_own_oracle_and_archive_group_evidence():
    rows = {row["name"]: row for row in checklist({})}
    for i, group in enumerate(((25, 33, 39, 44), (56, 73, 74, 77), (101, 123, 125, 130), (141,))):
        for n in group:
            name = f"gtja191_{n:03d}"
            cases = [c for check in rows[name]["checks"] for c in check["cases"]]
            own = "tests.unit.test_gtja191_multistage"
            key = (own, f"test_multistage_research_archive_readonly_recompute[group{i}]")
            evidence = {tuple(c["id"].split("::")): "passed" for c in cases}
            assert key in evidence
            assert (own, f"test_multistage_real_ten_stock_default_values[{n}]") in evidence
            del evidence[key]
            actual = next(row for row in checklist(evidence) if row["name"] == name)
            assert actual["kernel_evidence"] == "incomplete"


def test_nested_ranks_require_own_oracle_and_archive_evidence():
    rows = {row["name"]: row for row in checklist({})}
    for i, group in enumerate(((64, 119, 121, 138), (140, 157, 159))):
        for n in group:
            name = f"gtja191_{n:03d}"
            cases = [c for check in rows[name]["checks"] for c in check["cases"]]
            own = "tests.unit.test_gtja191_nested_ranks"
            required = [
                (own, f"test_nested_research_archive_readonly_recompute[group{i}]"),
                (own, f"test_nested_real_ten_stock_default_values[{n}]"),
                (own, "test_nested_rank_contrast_exact_zero_and_time_rank_weights"),
            ]
            full = {tuple(c["id"].split("::")): "passed" for c in cases}
            for key in required:
                assert key in full
                evidence = dict(full)
                del evidence[key]
                actual = next(row for row in checklist(evidence) if row["name"] == name)
                assert actual["kernel_evidence"] == "incomplete"


def test_literal_formulas_require_own_hand_and_archive_evidence():
    for number in (28, 54, 190):
        name = f"gtja191_{number:03d}"
        row = next(r for r in checklist({}) if r["name"] == name)
        cases = [c for check in row["checks"] for c in check["cases"]]
        full = {tuple(c["id"].split("::")): "passed" for c in cases}
        for key in full:
            assert key[0] == "tests.unit.test_gtja191_literal"
            evidence = dict(full)
            del evidence[key]
            actual = next(r for r in checklist(evidence) if r["name"] == name)
            assert actual["kernel_evidence"] == "incomplete"
