"""A checklist cannot turn absent, skipped or conflicting evidence into passes."""

from scripts.factor_acceptance_report import checklist, gate, read_evidence


def test_missing_evidence_is_incomplete_for_every_factor():
    rows = checklist({})
    assert len(rows) == 330
    assert all(r["kernel_evidence"] == "incomplete" for r in rows)
    assert all(r["full_goal_acceptance"] == "not_established" for r in rows)
    assert len([r for r in rows if r["library"] == "qlib_alpha158"]) == 158
    assert len([r for r in rows if r["library"] == "gtja191"]) == 153


def test_partial_and_skipped_cases_cannot_pass_the_gate():
    evidence = {("m", "a"): "passed", ("m", "b"): "skipped"}
    assert gate(evidence, "x", "m", ["a"])["status"] == "passed"
    for names in ([], ["a", "b"], ["a", "c"]):
        assert gate(evidence, "x", "m", names)["status"] == "incomplete"


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
