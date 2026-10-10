"""Audit fails closed; synthetic signatures, never executing external code."""

import pytest

from scripts.audit_alpha_reference import inventory


def test_all_ids_required_once_and_sorted():
    text = "def WQAlpha2(close){ return close }\ndef WQAlpha1(close){ return close }"
    rows = inventory(text, "WQAlpha", 2)
    assert [row["number"] for row in rows] == [1, 2]
    assert not any(row["count_as_available"] for row in rows)


@pytest.mark.parametrize(
    "text",
    [
        "def WQAlpha1(close){ close }",
        "def WQAlpha1(close){ close }\ndef WQAlpha1(close){ close }",
        "def WQAlpha1(close){ close }\ndef WQAlpha3(close){ close }",
    ],
)
def test_incomplete_or_duplicate_ids_rejected(text):
    with pytest.raises(ValueError):
        inventory(text, "WQAlpha", 2)


def test_real_extra_risk_fields_and_industry_dependency_not_hidden():
    text = "def X1(close, MKT, SMB, HML, indclass){\nreturn contextby{a, indclass.row(0)}\n}"
    row = inventory(text, "X", 1)[0]
    assert row["reference_inputs"] == ["close", "MKT", "SMB", "HML", "indclass"]
    assert row["reference_has_cross_section_operator"]
    assert "timestamp_aligned_value_risk_factor" in row["dependency_review"]
    assert "reference_uses_first_industry_row_not_point_in_time" in row["dependency_review"]


def test_comments_not_treated_as_actual_operators():
    text = "def X1(close){\n// rowRank(close)\n/* contextby */\nreturn close\n}"
    assert not inventory(text, "X", 1)[0]["reference_has_cross_section_operator"]
