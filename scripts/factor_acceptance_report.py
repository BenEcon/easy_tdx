"""Emit a per-definition evidence checklist from pytest JUnit, never an approval.

Run with the project's Python: python -m scripts.factor_acceptance_report report.xml.
Reads test evidence and current catalog only; does not calculate or fetch market data.
Missing/skipped cases cannot become passes. This is local kernel evidence, not full
goal acceptance, PIT/suspension coverage or deployment evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from easy_tdx.factor import list_factors
from easy_tdx.factor.builtin.alpha158 import SPECS
from easy_tdx.factor.builtin_parameters import TEMPLATES


def read_evidence(paths: list[Path]) -> dict[tuple[str, str], str]:
    evidence: dict[tuple[str, str], str] = {}
    priority = {"passed": 0, "skipped": 1, "failed": 2}
    for path in paths:
        for case in ET.parse(path).iter("testcase"):
            key = (case.get("classname", ""), case.get("name", ""))
            state = (
                "failed"
                if case.find("failure") is not None or case.find("error") is not None
                else "skipped"
                if case.find("skipped") is not None
                else "passed"
            )
            # Merging a later pass must not hide a supplied failure or skip.
            if key not in evidence or priority[state] > priority[evidence[key]]:
                evidence[key] = state
    return evidence


def gate(
    evidence: dict[tuple[str, str], str], label: str, module: str, names: list[str]
) -> dict[str, Any]:
    cases = [
        {"id": f"{module}::{name}", "status": evidence.get((module, name), "not_run")}
        for name in names
    ]
    return {
        "check": label,
        "status": "passed"
        if cases and all(c["status"] == "passed" for c in cases)
        else "incomplete",
        "cases": cases,
    }


def checklist(evidence: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
    # This inventory uses the repository's actual, hash-checked unit fixtures.
    fixtures = sorted(
        p.name
        for p in (Path(__file__).resolve().parents[1] / "tests/fixtures/factor_units").glob(
            "*.json"
        )
    )
    rows = []
    for item in list_factors():
        if item["alias_of"]:
            continue
        name = item["name"]
        checks = []
        if item["library"] == "qlib_alpha158":
            key = name.removeprefix("alpha158_").upper()
            spec = SPECS[key]
            old = "tests.unit.test_alpha158"
            new = "tests.unit.test_alpha158_boundaries"
            checks = [
                gate(
                    evidence,
                    "默认公式独立计算",
                    old,
                    [f"test_every_formula_every_default_window_against_independent_oracle[{key}]"],
                ),
                gate(
                    evidence,
                    "前缀因果",
                    old,
                    [f"test_every_formula_is_causal_and_missing_window_is_not_filled[{key}]"],
                ),
                gate(
                    evidence,
                    "全部声明输入缺失与异常",
                    new,
                    [
                        f"test_every_declared_dependency_requires_complete_valid_window[{bad}-{key}-{field}]"
                        for bad in ("nan", "inf", "-1.0")
                        for field in spec.inputs
                    ],
                ),
                gate(
                    evidence,
                    "常数与零量",
                    new,
                    [
                        f"test_every_constant_window_has_explicit_mathematical_result[{v}-{key}]"
                        for v in ("0.0", "100.0")
                    ],
                ),
                gate(
                    evidence,
                    "不补日历缺口",
                    new,
                    [f"test_bar_windows_do_not_fill_missing_calendar_rows[{key}]"],
                ),
                gate(
                    evidence,
                    "空短窗口及缺字段",
                    new,
                    [f"test_short_empty_and_absent_required_columns_are_not_fake_results[{key}]"],
                ),
                gate(
                    evidence,
                    "真实冻结行情全行独立对照",
                    new,
                    [
                        f"test_every_qualified_real_value_against_independent_oracle[{f}]"
                        for f in fixtures
                        if "vwap" not in spec.inputs or f.endswith("-NONE.json")
                    ],
                ),
            ]
            if spec.window is not None:
                checks.append(
                    gate(
                        evidence,
                        "自定义窗口独立计算",
                        "tests.unit.test_factor_parameters",
                        [
                            f"test_every_registered_window_accepts_custom_window_and_independent_oracle[{key}]"
                        ],
                    )
                )
        elif item["library"] == "gtja191":
            number = int(name.removeprefix("gtja191_"))
            module = "tests.unit.test_gtja191"
            if number in {6, 185}:
                checks = [
                    gate(
                        evidence,
                        "截面排名、并列、缺失与前缀",
                        module,
                        [f"test_whole_pool_rank_hand_oracle_ties_missing_and_append[{number}]"],
                    ),
                    gate(
                        evidence,
                        "真实三股票截面独立对照",
                        module,
                        [
                            f"test_panel_real_frozen_three_stock_oracle[{adjust}-{number}]"
                            for adjust in ("NONE", "QFQ", "HFQ")
                        ],
                    ),
                ]
                if number == 6:
                    checks.append(
                        gate(
                            evidence,
                            "十进制加权价相等不产生虚假方向",
                            module,
                            ["test_alpha006_decimal_equal_weighted_prices_remain_tied"],
                        )
                    )
            else:
                checks = [
                    gate(
                        evidence,
                        "独立公式与前缀",
                        module,
                        [
                            f"test_all_rows_independent_arithmetic_and_future_invariance[{number}-None]"
                        ],
                    ),
                    gate(
                        evidence,
                        "全部声明输入缺失／异常及恢复",
                        module,
                        [
                            f"test_declared_missing_invalid_fields_break_window_and_recover[{number}]"
                        ],
                    ),
                    gate(
                        evidence,
                        "常数／零量／空短输入",
                        module,
                        [f"test_constant_flat_zero_volume_and_short_inputs[{number}]"],
                    ),
                    gate(
                        evidence,
                        "真实冻结行情全行独立对照",
                        module,
                        [
                            f"test_all_supported_series_real_frozen_rows[{filename}]"
                            for filename in fixtures
                        ],
                    ),
                ]
                if item["parameters"]:
                    checks.append(
                        gate(
                            evidence,
                            "自定义窗口独立计算",
                            module,
                            [
                                f"test_all_rows_independent_arithmetic_and_future_invariance[{number}-{w}]"
                                for w in (3, 7)
                            ],
                        )
                    )
            if item["family"].startswith("sma_"):
                # Dedicated independent closed-weight oracle, not the finite
                # window scalar suite. Keep exact cases visible per formula.
                module = "tests.unit.test_gtja191_smoothing"
                checks = [
                    gate(
                        evidence,
                        "独立展开权重与前缀",
                        module,
                        [
                            f"test_independent_expanded_weights_every_row_and_causal_prefix[{w}-{number}]"
                            for w in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "全部输入断档重置与恢复",
                        module,
                        [
                            f"test_every_input_invalid_resets_state_and_recovers_like_fresh_history[{number}]"
                        ],
                    ),
                    gate(
                        evidence,
                        "常数零量空短输入",
                        module,
                        [f"test_flat_zero_volume_empty_and_short_are_explicit[{number}]"],
                    ),
                    gate(
                        evidence,
                        "真实冻结行情独立对照",
                        module,
                        [
                            f"test_all_recursive_formulas_real_frozen_independent_values[{filename}]"
                            for filename in fixtures
                        ],
                    ),
                    gate(
                        evidence,
                        "种子历史起点与原始公式差异",
                        module,
                        [
                            "test_seed_m2_original_formula_and_nested_publication_hand_cases",
                            "test_history_start_dependency_and_gap_reset_are_not_hidden",
                            "test_defaults_family_dedup_and_parameter_boundaries",
                            "test_zero_denominators_reset_derived_state_without_fake_values",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实行情自定义递归窗口",
                        module,
                        [
                            f"test_custom_recursive_windows_on_all_frozen_inputs[{w}-{filename}]"
                            for w in (3, 7)
                            for filename in fixtures
                        ],
                    ),
                    gate(
                        evidence,
                        "递归中途取消不返回部分成功",
                        module,
                        [
                            f"test_cancel_inside_recursive_loop_does_not_return_partial_output[{number}]"
                        ],
                    ),
                    gate(
                        evidence,
                        "整池日期对齐与独立标的状态",
                        module,
                        [
                            f"test_recursive_pool_alignment_and_independent_per_symbol_state[{number}]"
                        ],
                    ),
                ]
            if item["family"].startswith("compound_"):
                module = "tests.unit.test_gtja191_compound"
                checks = [
                    gate(
                        evidence,
                        "独立复合公式、改参与因果前缀",
                        module,
                        [
                            f"test_independent_compound_values_and_future_prefix[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "完整输入边界与断档恢复",
                        module,
                        [
                            f"test_all_compound_inputs_missing_invalid_and_recovery[{number}]",
                            f"test_compound_empty_short_constant_and_zero_volume[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实冻结行情默认与多参数",
                        module,
                        [
                            f"test_compound_all_real_frozen_defaults_and_custom[{filename}]"
                            for filename in fixtures
                        ],
                    ),
                    gate(
                        evidence,
                        "手算排名权重及原公式差异",
                        module,
                        [
                            "test_rank_ties_complete_windows_and_exponential_weight_hand_cases",
                            "test_compound_original_parallel_smoothing_and_history_start",
                            "test_named_parameters_metadata_limits_no_default_mutation",
                            f"test_each_named_window_partial_override_and_definition_fingerprint[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "整池隔离与取消",
                        module,
                        [
                            f"test_compound_pool_per_symbol_state_and_date_alignment[{number}]",
                            f"test_compound_cancellation_no_partial_success[{number}]",
                        ],
                    ),
                ]
                if number in {111, 164}:
                    checks.append(
                        gate(
                            evidence,
                            "零价格区间重置派生平滑",
                            module,
                            [f"test_zero_price_range_resets_compound_smoothing[{number}]"],
                        )
                    )
            if number in {4, 5, 22, 23, 38, 55, 70, 78, 95, 98, 132, 137, 144, 172, 186}:
                module = "tests.unit.test_gtja191_conditional"
                checks = [
                    gate(
                        evidence,
                        "独立条件公式、改参与前缀",
                        module,
                        [
                            f"test_independent_conditional_values_and_prefix[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "全部输入、断档恢复、常数与零分母",
                        module,
                        [
                            f"test_conditional_inputs_gaps_recovery[{number}]",
                            f"test_conditional_constant_zero_empty_short[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实冻结行情全行默认及自定义",
                        module,
                        [f"test_conditional_frozen_all_rows_and_parameters[{f}]" for f in fixtures],
                    ),
                    gate(
                        evidence,
                        "参数逐项编辑、整池隔离及取消",
                        module,
                        [
                            f"test_conditional_metadata_partial_parameters[{number}]",
                            f"test_conditional_pool_isolation[{number}]",
                            f"test_conditional_cancellation_no_partial_success[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "手算边界、精确分支与历史巨量恢复",
                        module,
                        [
                            "test_conditional_exact_thresholds_ties_and_zero_denominators",
                            "test_conditional_price_branches_and_stale_outlier_std",
                        ],
                    ),
                ]
                if number in {70, 95, 132, 144}:
                    checks.append(
                        gate(
                            evidence,
                            "实际金额单位来源及失败隔离",
                            module,
                            ["test_gtja_amount_qualification_is_not_a_price_volume_proxy"],
                        )
                    )
                if number in {22, 23, 38, 55, 78, 98, 137, 172, 186}:
                    checks.append(
                        gate(
                            evidence,
                            "长历史真实价格及200根预热",
                            module,
                            [
                                f"test_long_frozen_price_formulas_including_200_bar_warmup[{case}]"
                                for case in (
                                    "300450-qfq-20261002",
                                    "600699-qfq-20260929",
                                    "601698-min30-qfq-20261002",
                                )
                            ],
                        )
                    )
            if item["family"].startswith("panel_"):
                module = "tests.unit.test_gtja191_panel_compound"
                checks = [
                    gate(
                        evidence,
                        "精确并列手算、缺失布尔值及中间断档",
                        module,
                        [
                            "test_panel_rank_moments_preserve_exact_permutation_ties_without_epsilon",
                            "test_panel_148_affine_translation_is_an_exact_rank_tie",
                            "test_panel_boolean_missing_is_not_false_and_skipped_gap_not_ranked",
                            f"test_panel_subset_membership_is_explicit_and_all_ranks_recomputed[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "独立矩阵公式、全部日期、窗口、前缀与股票顺序",
                        module,
                        [
                            f"test_panel_independent_defaults_custom_future_and_permutation[{size}-{number}]"
                            for size in ("None", "3", "7")
                        ],
                    ),
                    gate(
                        evidence,
                        "缺日期、所有输入异常、常数、零量与完整预热",
                        module,
                        [f"test_panel_all_inputs_invalid_missing_date_constant_and_zero[{number}]"],
                    ),
                    gate(
                        evidence,
                        "三股票真实冻结行情三种复权",
                        module,
                        [
                            f"test_panel_frozen_three_stock_all_adjustments[{number}-{adjust}]"
                            for adjust in ("NONE", "QFQ", "HFQ")
                        ],
                    ),
                    gate(
                        evidence,
                        "命名参数、单股拒绝与取消",
                        module,
                        [
                            "test_panel_named_parameters_catalog_and_no_single_stock_substitute",
                            f"test_panel_cancellation_is_not_partial_success[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "实际股票池原档只读、冻结显式重算",
                        module,
                        [f"test_panel_research_archive_readonly_recompute_all[{number}]"],
                    ),
                ]
            else:
                checks.append(
                    gate(
                        evidence,
                        "实际内核原档只读与显式重算",
                        "tests.unit.test_gtja191_archive",
                        ["test_gtja_panel_and_series_joint_research_archive"]
                        if number in {6, 185}
                        else [
                            f"test_every_gtja_series_freezes_and_recomputes_without_live_data[{name}]"
                        ],
                    )
                )
            if "vwap" in item["data_requirements"]:
                module = "tests.unit.test_gtja191_vwap"
                checks = [
                    gate(
                        evidence,
                        "独立公式、默认及改参、因果前缀与标的顺序",
                        module,
                        [
                            f"test_vwap_independent_defaults_custom_future_and_permutation[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "全部输入异常、缺日、常数、零量及恢复",
                        module,
                        [
                            f"test_vwap_invalid_inputs_missing_date_constant_zero_and_recovery[{number}]",
                            "test_vwap_hand_weights_power_missing_boolean_and_nested_division",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实不复权成交量额核验与冻结逐值对照",
                        module,
                        [
                            f"test_vwap_real_qualified_none_daily_minute_and_zero_transactions[{number}]",
                            f"test_vwap_long_real_default_windows_have_observed_values[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "参数元数据、拒绝复权和缺字段、取消",
                        module,
                        [
                            f"test_vwap_metadata_parameters_adjustment_rejection_and_missing[{number}]",
                            f"test_vwap_cancellation_no_partial_success[{number}]",
                            "test_vwap_inventory_not_panel_substitutes",
                        ],
                    ),
                    gate(
                        evidence,
                        "实际原档只读及无实时取数复算",
                        module,
                        ["test_vwap_panel_real_evaluation_freeze_readonly_and_recompute"],
                    ),
                ]
                if number == 36:
                    checks.append(
                        gate(
                            evidence,
                            "滚动和精确零并列回归",
                            module,
                            ["test_vwap_036_window_sum_preserves_exact_zero_rank_tie"],
                        )
                    )
                if number in {16, 36, 90, 179}:
                    checks.append(
                        gate(
                            evidence,
                            "真实常数排名不填零",
                            module,
                            [
                                f"test_vwap_real_constant_price_ranks_are_undefined_not_zero[{number}]"
                            ],
                        )
                    )
            if number in {35, 61, 87, 92, 156}:
                module = "tests.unit.test_gtja191_linear_decay"
                checks = [
                    gate(
                        evidence,
                        "独立线性加权公式、默认改参、因果前缀与标的顺序",
                        module,
                        [
                            f"test_decay_independent_defaults_custom_causal_and_order[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "输入缺失、完整窗口、零分母及不跳过缺失分支",
                        module,
                        [
                            f"test_decay_invalid_fields_dates_constant_zero_recovery[{number}]",
                            "test_decay_hand_weights_missing_branch_and_zero_denominator",
                        ],
                    ),
                    gate(
                        evidence,
                        "十股真实不复权冻结行情逐行独立对照",
                        module,
                        [
                            f"test_decay_real_ten_stock_default_values[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "中文元数据、默认预热、参数及输入限制、取消",
                        module,
                        [
                            f"test_decay_metadata_reject_single_missing_adjusted_and_cancel[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "实际研究原档只读及冻结重算",
                        module,
                        [
                            "test_decay_research_archive_readonly_recompute",
                        ],
                    ),
                ]
                if number == 61:
                    checks.append(
                        gate(
                            evidence,
                            "线性加权排名精确并列及变动成员数",
                            module,
                            ["test_decay_061_exact_rank_weight_ties_and_changing_membership"],
                        )
                    )
            boundary_cases = {
                21: ["test_regression_uses_mean_close_not_reference_modules_raw_close"],
                147: ["test_regression_uses_mean_close_not_reference_modules_raw_close"],
                86: ["test_acceleration_exact_decimal_zero_and_threshold"],
                103: ["test_extreme_distance_zero_based_recent_ties"],
                133: ["test_extreme_distance_zero_based_recent_ties"],
                177: ["test_extreme_distance_zero_based_recent_ties"],
                139: ["test_correlation_and_slope_large_offset_and_constants"],
                116: ["test_correlation_and_slope_large_offset_and_constants"],
                127: ["test_nested_peak_rms_has_two_complete_windows"],
                191: ["test_volume_mean_correlation_uses_fixed_five_outer_bars"],
                158: ["test_power_ratio_is_price_scale_invariant_without_intermediate_overflow"],
                171: ["test_power_ratio_is_price_scale_invariant_without_intermediate_overflow"],
            }.get(number, [])
            if number in {40, 49, 50, 51, 69, 76, 112, 128, 139}:
                boundary_cases.append("test_conditional_pressure_ties_and_denominator_semantics")
            if number in {49, 50, 51, 128}:
                boundary_cases.append(
                    "test_decimal_equal_price_sums_are_not_false_directional_money_flow"
                )
            if boundary_cases:
                checks.append(
                    gate(
                        evidence,
                        "原公式差异与手算边界",
                        "tests.unit.test_gtja191_rolling_boundaries",
                        boundary_cases,
                    )
                )
        elif name in TEMPLATES:
            module = "tests.unit.test_builtin_factor_parameters"
            checks = [
                gate(
                    evidence,
                    "默认与自定义公式及前缀",
                    module,
                    [
                        f"test_every_builtin_actual_kernel_matches_independent_oracle_and_is_causal[{v}-{name}]"
                        for v in ("False", "True")
                    ],
                ),
                gate(
                    evidence,
                    "真实冻结行情自定义窗口",
                    module,
                    [
                        f"test_custom_parameters_on_real_frozen_stocks_periods_and_adjustments[{name}-{Path(f).stem}]"
                        for f in fixtures
                    ],
                ),
            ]
            if name == "obv_trend":
                checks.append(
                    gate(
                        evidence,
                        "OBV 专项回归",
                        "tests.unit.test_factor_obv_window",
                        [
                            "test_hand_calculated_ties_gaps_and_units",
                            "test_old_extreme_volume_does_not_destroy_local_precision",
                            "test_changed_semantics_are_versioned_without_changing_other_factors",
                            "test_legacy_obv_archive_remains_read_only_and_explicit_replay_records_new_version",
                        ],
                    )
                )
        rows.append(
            {
                "name": name,
                "display_name": item["display_name"],
                "library": item["library"],
                "implemented": item["implemented"],
                "implementation_version": item["implementation_version"],
                "definition_sha256": item["formula_sha256"],
                "checks": checks,
                "kernel_evidence": "passed_listed_checks"
                if checks and all(c["status"] == "passed" for c in checks)
                else "incomplete",
                "full_goal_acceptance": "not_established",
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path, nargs="+")
    args = parser.parse_args()
    report = {
        "format": "factor-kernel-evidence-v1",
        "scope": (
            "仅列出的公式证据；不证明完整因子验收、真实停牌、PIT 或部署。"
            "JUnit 须与当前源码配套保存。"
        ),
        "evidence": [
            {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in args.junit
        ],
        "factors": checklist(read_evidence(args.junit)),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
