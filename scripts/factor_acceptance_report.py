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
        if item["library"] == "alpha101":
            number = int(name[-3:])
            module = "tests.unit.test_alpha101"
            cases = [
                f"test_alpha101_independent_prefix_and_parameters[False-{number}]",
                f"test_alpha101_independent_prefix_and_parameters[True-{number}]",
                f"test_alpha101_metadata_validation_and_no_mutation[{number}]",
                "test_alpha101_hand_examples_and_ties",
                "test_alpha101_cancellation_and_relative_scale",
            ]
            if number in {3, 4}:
                cases += [
                    f"test_alpha101_real_panel_oracle[{number}]",
                    "test_alpha101_joint_pool_archive",
                ]
            else:
                cases += [
                    f"test_alpha101_missing_invalid_constant_and_recovery[{number}]",
                    f"test_alpha101_series_archive_readonly_recompute[{number}]",
                    *[
                        f"test_alpha101_real_three_adjustment_oracle[{number}-{adjust}]"
                        for adjust in ("NONE", "QFQ", "HFQ")
                    ],
                ]
            checks = [
                gate(
                    evidence,
                    "本地适配：独立数值、边界、真实价格与存档（生产许可待复核）",
                    module,
                    cases,
                )
            ]
            if number in {2, 10, 13, 16, 22, 33, 38, 40, 44, 46, 49, 51, 54}:
                module = "tests.unit.test_alpha101_second"
                cases = [
                    f"test_second_default_custom_independent_prefix_permutation[False-{number}]",
                    f"test_second_default_custom_independent_prefix_permutation[True-{number}]",
                    f"test_second_every_input_missing_invalid_constant_and_recovery[{number}]",
                    f"test_second_metadata_validation_identity_and_no_mutation[{number}]",
                    f"test_second_real_pool_and_minute[{number}]",
                    f"test_second_frozen_archive_readonly_recompute[{number}]",
                    "test_second_alias_reuse_and_parameter_duplicates",
                    "test_second_hand_thresholds_ties_zero_volume_and_scale",
                    "test_second_midway_cancellation",
                    "test_second_proportional_volume_and_return_ties_do_not_create_correlation",
                    "test_second_ratio_ranks_survive_overflow_and_close_ratios",
                ]
                if number in {46, 49, 51, 54}:
                    cases += [
                        f"test_second_real_three_adjustments[{a}-{number}]"
                        for a in ("NONE", "QFQ", "HFQ")
                    ]
                checks = [
                    gate(
                        evidence,
                        "本地适配及跨库复用：独立预期／边界／冻结数据／存档",
                        module,
                        cases,
                    )
                ]
            if number in {14, 15, 18, 20, 35, 37}:
                module = "tests.unit.test_alpha101_third"
                cases = [
                    f"test_third_independent_default_custom_prefix_permutation[{custom}-{number}]"
                    for custom in (False, True)
                ] + [
                    f"test_third_missing_invalid_constant_and_zero_volume[{number}]",
                    f"test_third_metadata_parameters_scope_and_isolation[{number}]",
                    f"test_third_frozen_ten_stocks_and_minute[{number}]",
                    f"test_third_frozen_archive_readonly_recompute[{number}]",
                    *[
                        f"test_third_real_adjustments[{adjust}-{number}]"
                        for adjust in ("NONE", "QFQ", "HFQ")
                    ],
                    "test_third_aliases_and_distinct_body_std_defaults",
                    "test_third_014_correlation_not_covariance_and_scale",
                    "test_third_cancellation_is_not_success",
                ]
                checks = [
                    gate(evidence, "本地跨库适配：独立公式／边界／冻结数据／存档", module, cases)
                ]
            if number in {8, 19, 26, 30, 34, 45}:
                module = "tests.unit.test_alpha101_fourth"
                cases = [
                    f"test_fourth_default_custom_independent_prefix_permutation[{custom}-{number}]"
                    for custom in (False, True)
                ] + [
                    f"test_fourth_missing_invalid_constant_and_zero[{number}]",
                    f"test_fourth_metadata_limits_empty_scope_and_no_mutation[{number}]",
                    f"test_fourth_frozen_pool_and_minute[{number}]",
                    f"test_fourth_frozen_archive_readonly_recompute[{number}]",
                    *[
                        f"test_fourth_real_adjustments[{adjust}-{number}]"
                        for adjust in ("NONE", "QFQ", "HFQ")
                    ],
                    "test_fourth_exact_nested_ties_extreme_scale_and_boundaries",
                    "test_fourth_nested_ties_and_volume_sum_overflow",
                    "test_fourth_midway_cancel_and_compound_source_fingerprint",
                ]
                checks = [
                    gate(
                        evidence,
                        "本地复合窗口：独立公式／精确并列／边界／真实数据／原档",
                        module,
                        cases,
                    )
                ]
            if number in {24, 41, 42, 50, 55}:
                module = "tests.unit.test_alpha101_fifth"
                cases = [
                    f"test_fifth_independent_prefix_permutation[{custom}-{number}]"
                    for custom in (False, True)
                ] + [
                    f"test_fifth_invalid_missing_constant_recovery[{number}]",
                    f"test_fifth_metadata_parameter_scope_and_mutation[{number}]",
                    f"test_fifth_real_frozen_pool_minute[{number}]",
                    f"test_fifth_archive_readonly_and_frozen_recompute[{number}]",
                    "test_fifth_threshold_equality_exact_large_values_and_alias_sign",
                    "test_fifth_midway_cancellation",
                ]
                if number in {24, 55}:
                    cases += [
                        f"test_fifth_real_adjustments[{a}-{number}]" for a in ("NONE", "QFQ", "HFQ")
                    ]
                else:
                    cases += [f"test_fifth_vwap_adjustments_are_not_silently_converted[{number}]"]
                checks = [
                    gate(evidence, "条件阈值／负号区分／VWAP边界／冻结数据与原档", module, cases)
                ]
            if number in {5, 11, 27, 52}:
                module = "tests.unit.test_alpha101_sixth"
                cases = [
                    f"test_sixth_independent_prefix_and_permutation[{custom}-{number}]"
                    for custom in (False, True)
                ] + [
                    f"test_sixth_invalid_missing_constant_recovery[{number}]",
                    f"test_sixth_metadata_configuration_identity_and_limits[{number}]",
                    f"test_sixth_real_frozen_default_pool_and_minute[{number}]",
                    f"test_sixth_archive_readonly_frozen_recompute[{number}]",
                    "test_sixth_absolute_rank_threshold_and_reference_window_distinctions",
                    "test_sixth_midway_cancellation_and_exact_ties",
                ]
                if number == 52:
                    cases += [
                        f"test_sixth_052_real_adjustments[{a}]" for a in ("NONE", "QFQ", "HFQ")
                    ]
                checks = [
                    gate(
                        evidence,
                        "绝对值位置／排名阈值／收益窗口差异／真实数据与原档",
                        module,
                        cases,
                    )
                ]
            if number in {32, 57, 60}:
                module = "tests.unit.test_alpha101_seventh"
                cases = [
                    f"test_seventh_independent_prefix_and_permutation[{custom}-{number}]"
                    for custom in (False, True)
                ] + [
                    f"test_seventh_invalid_constant_missing_and_recovery[{number}]",
                    f"test_seventh_metadata_parameter_and_scope[{number}]",
                    f"test_seventh_real_frozen_default_pool_and_minute[{number}]",
                    f"test_seventh_archive_readonly_frozen_recompute[{number}]",
                    "test_seventh_position_ties_decay_scale_and_non_alias",
                    "test_seventh_cancellation_and_extreme_scale",
                ]
                if number == 60:
                    cases += [
                        f"test_seventh_060_real_adjustments[{a}]" for a in ("NONE", "QFQ", "HFQ")
                    ]
                checks = [
                    gate(evidence, "极值位置／并列／线性衰减／独立归一化与存档", module, cases)
                ]
        elif item["library"] == "qlib_alpha158":
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
            if number in {25, 33, 39, 44, 56, 73, 74, 77, 101, 123, 125, 130, 141}:
                module = "tests.unit.test_gtja191_multistage"
                group_index = next(
                    i
                    for i, group in enumerate(
                        ((25, 33, 39, 44), (56, 73, 74, 77), (101, 123, 125, 130), (141,))
                    )
                    if number in group
                )
                checks = [
                    gate(
                        evidence,
                        "独立嵌套公式、默认改参、因果前缀与顺序",
                        module,
                        [
                            f"test_multistage_independent_defaults_custom_causal_order[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "全部输入异常、缺日、常数、零量与恢复",
                        module,
                        [f"test_multistage_invalid_missing_constant_zero_recovery[{number}]"],
                    ),
                    gate(
                        evidence,
                        "十股真实冻结默认窗口逐值核验",
                        module,
                        [f"test_multistage_real_ten_stock_default_values[{number}]"],
                    ),
                    gate(
                        evidence,
                        "元数据、预热、输入复权限制与取消",
                        module,
                        [f"test_multistage_metadata_inputs_adjustment_cancel[{number}]"],
                    ),
                    gate(
                        evidence,
                        "实际研究原档只读与禁止实时取数复算",
                        module,
                        [
                            f"test_multistage_research_archive_readonly_recompute[group{group_index}]"
                        ],
                    ),
                ]
                if number == 33:
                    checks.append(
                        gate(
                            evidence,
                            "原研报括号手算与长短窗口约束",
                            module,
                            [
                                "test_multistage_033_report_parentheses_change_rank",
                                "test_multistage_033_long_short_constraint",
                            ],
                        )
                    )
                if number == 44:
                    checks.append(
                        gate(
                            evidence,
                            "真实分钟时序而非截面替代",
                            module,
                            [
                                "test_multistage_044_real_minute_is_single_series_not_pool_rank",
                            ],
                        )
                    )
            if number in {64, 119, 121, 138, 140, 157, 159}:
                module = "tests.unit.test_gtja191_nested_ranks"
                group_index = 0 if number in {64, 119, 121, 138} else 1
                checks = [
                    gate(
                        evidence,
                        "嵌套公式独立预期、默认改参、因果与顺序",
                        module,
                        [
                            f"test_nested_independent_defaults_custom_causal_order[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "异常输入、缺日、常数零量与恢复",
                        module,
                        [
                            f"test_nested_invalid_missing_constant_zero_recovery[{number}]",
                            "test_nested_rank_contrast_exact_zero_and_time_rank_weights",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实十股逐值与无定义缺失核验（不保证有有限值）",
                        module,
                        [f"test_nested_real_ten_stock_default_values[{number}]"],
                    ),
                    gate(
                        evidence,
                        "元数据、完整预热、输入复权及取消",
                        module,
                        [f"test_nested_metadata_inputs_adjustment_cancel[{number}]"],
                    ),
                    gate(
                        evidence,
                        "实际研究原档只读与无取数复算",
                        module,
                        [f"test_nested_research_archive_readonly_recompute[group{group_index}]"],
                    ),
                ]
                if number == 159:
                    checks.append(
                        gate(
                            evidence,
                            "原表权重手算及真实分钟",
                            module,
                            [
                                "test_nested_159_literal_weights_and_parameter_order",
                                "test_nested_159_real_minute_single_series",
                            ],
                        )
                    )
            if number in {28, 54, 190}:
                module = "tests.unit.test_gtja191_literal"
                checks = [
                    gate(
                        evidence,
                        "原表口径默认改参独立预期与前缀",
                        module,
                        [
                            f"test_literal_defaults_custom_prefix_permutation[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "逐输入异常、缺日、常数与恢复",
                        module,
                        [
                            f"test_literal_invalid_missing_constant_and_recovery[{number}]",
                            f"test_literal_metadata_parameters_and_single_scope[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实三复权日线及可用分钟（单股不能冒充股票池）",
                        module,
                        [
                            f"test_literal_real_stocks_periods_adjustments[{adjust}-{number}]"
                            for adjust in ("NONE", "QFQ", "HFQ")
                        ],
                    ),
                    gate(
                        evidence,
                        "原文差异手算与冻结原档",
                        module,
                        [
                            "test_literal_research_archive_readonly_recompute",
                            "test_literal_190_asymmetric_hand_counts_and_exact_ties"
                            if number == 190
                            else "test_literal_hand_distinct_denominators_and_correlation_ties",
                        ],
                    ),
                ]
            if number == 143:
                module = "tests.unit.test_gtja191_self_recursion"
                checks = [
                    gate(
                        evidence,
                        "独立有理数乘积、种子手算、历史起点及数值上下溢恢复",
                        module,
                        [
                            "test_self_hand_seed_constant_and_history_origin",
                            "test_self_underflow_overflow_preserves_state_and_decimal_ties",
                            "test_self_pool_prefix_permutation_missing_dates_and_inputs",
                            "test_self_tiny_research_values_are_not_collapsed_to_zero",
                        ],
                    ),
                    gate(
                        evidence,
                        "全部价格异常重置与声明／中途取消",
                        module,
                        [
                            "test_self_metadata_and_midway_cancellation",
                            *[
                                f"test_self_invalid_prices_reset_and_recover[{v}]"
                                for v in ("nan", "inf", "-inf", "0.0", "-1.0")
                            ],
                        ],
                    ),
                    gate(
                        evidence,
                        "真实三复权、多股票、日线与分钟",
                        module,
                        [
                            f"test_self_real_stocks_periods_adjustments[{a}]"
                            for a in ("NONE", "QFQ", "HFQ")
                        ],
                    ),
                    gate(
                        evidence,
                        "原档只读、禁实时冻结重算",
                        module,
                        [
                            "test_self_research_archive_readonly_recompute",
                        ],
                    ),
                    gate(
                        evidence,
                        "单股原档只读与显式重算",
                        "tests.unit.test_gtja191_archive",
                        [
                            "test_every_gtja_series_freezes_and_recomputes_without_live_data[gtja191_143]",
                        ],
                    ),
                ]
            if number == 30:
                module = "tests.unit.test_gtja191_risk_residuals"
                checks = [
                    gate(
                        evidence,
                        "独立回归与正交手算、默认改参和因果前缀",
                        module,
                        [
                            "test_risk_hand_orthogonal_design",
                            *[
                                f"test_risk_default_custom_independent_and_prefix[{r}-{s}]"
                                for r, s in ((60, 20), (5, 1), (8, 3), (20, 7))
                            ],
                        ],
                    ),
                    gate(
                        evidence,
                        "缺失、秩亏、尺度、取消及恢复",
                        module,
                        [
                            "test_risk_gaps_rank_constant_and_recovery",
                            "test_risk_cancellation",
                            "test_risk_scaling_does_not_change_regression[1e-150]",
                            "test_risk_scaling_does_not_change_regression[1e+150]",
                            "test_risk_ill_conditioned_not_silently_regularized",
                            *[
                                f"test_risk_invalid_close_rewarms_all_dependencies[{value}]"
                                for value in ("0.0", "-1.0", "nan", "inf")
                            ],
                        ],
                    ),
                    gate(
                        evidence,
                        "三复权真实价格但合成风险输入（非真实风险数据验收）",
                        module,
                        [
                            f"test_risk_real_prices_synthetic_factors_oracle[{a}]"
                            for a in ("NONE", "QFQ", "HFQ")
                        ],
                    ),
                    gate(
                        evidence,
                        "缺数据禁用及原始输入只读再算",
                        module,
                        [
                            "test_risk_metadata_and_missing_data_are_not_false_availability",
                            "test_risk_web_refuses_missing_source",
                            "test_risk_raw_snapshot_readonly_and_explicit_kernel_recompute",
                        ],
                    ),
                ]
            if number in {146, 165, 166, 183}:
                module = "tests.unit.test_gtja191_window_interpretations"
                checks = [
                    gate(
                        evidence,
                        "公开解释默认／改参、独立算式与因果前缀",
                        module,
                        [
                            f"test_interpreted_default_custom_oracle_prefix[{size}-{number}]"
                            for size in ("None", 3, 7)
                        ],
                    ),
                    gate(
                        evidence,
                        "缺失常数、数值尺度、中途取消与手算",
                        module,
                        [
                            f"test_interpreted_missing_constant_extreme_and_cancel[{number}]",
                            "test_interpreted_hand_examples_and_invalid_windows",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实多股多周期三复权",
                        module,
                        [
                            f"test_interpreted_real_periods_adjustments[{a}-{number}]"
                            for a in ("NONE", "QFQ", "HFQ")
                        ],
                    ),
                    gate(
                        evidence,
                        "整池身份及公开解释元数据",
                        module,
                        [
                            f"test_interpreted_pool_identity_and_metadata[{number}]",
                            f"test_interpreted_declared_input_and_parameter_contract[{number}]",
                            "test_interpreted_equivalent_windows_are_not_duplicate_factors",
                        ],
                    ),
                    gate(
                        evidence,
                        "冻结原档禁止实时取数重算",
                        "tests.unit.test_gtja191_archive",
                        [
                            f"test_every_gtja_series_freezes_and_recomputes_without_live_data[gtja191_{number:03d}]"
                        ],
                    ),
                ]
            if number in {149, 181}:
                module = "tests.unit.test_gtja191_benchmark_statistics"
                windows = (2, 7, 252) if number == 149 else (1, 3, 20)
                checks = [
                    gate(
                        evidence,
                        "独立默认／改参公式与未来前缀",
                        module,
                        [
                            f"test_default_custom_independent_formula_and_prefix[{number}-{w}]"
                            for w in windows
                        ],
                    ),
                    gate(
                        evidence,
                        "缺失常数与中途取消",
                        module,
                        [
                            f"test_constant_invalid_missing_and_cancel[{number}]",
                            "test_filtered_beta_counts_selected_samples_holds_non_down_and_resets_gap"
                            if number == 149
                            else "test_signed_cubic_exact_zero_and_old_outlier_leaves_window",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实多周期三复权",
                        module,
                        [
                            f"test_real_multi_period_adjustments_and_independent_indices[{a}-{number}]"
                            for a in ("NONE", "QFQ", "HFQ")
                        ],
                    ),
                    gate(
                        evidence,
                        "800根真实默认参数多股独立对照",
                        module,
                        [
                            f"test_default_real_800_bars_multi_stock_independent_oracle[{name}-{number}]"
                            for name in (
                                "SZ-000001-stock.json",
                                "SZ-300750-stock.json",
                                "SH-600036-stock.json",
                            )
                        ],
                    ),
                    gate(
                        evidence,
                        "冻结输入显式重算",
                        "tests.unit.test_gtja191_archive",
                        [
                            f"test_every_gtja_series_freezes_and_recomputes_without_live_data[gtja191_{number:03d}]"
                        ],
                    ),
                ]
            if number in {75, 182}:
                module = "tests.unit.test_gtja191_benchmark"
                checks = [
                    gate(
                        evidence,
                        "独立窗口计数、参数预热与前缀",
                        module,
                        [
                            f"test_independent_window_oracle_custom_warmup_and_prefix[{w}-{number}]"
                            for w in (1, 3, 20, 50)
                        ],
                    ),
                    gate(
                        evidence,
                        "平盘／零分母／缺失与独立基准校验",
                        module,
                        [
                            f"test_hand_ties_constant_zero_denominator_and_missing_window[{number}]",
                            f"test_formula_requires_independent_source_and_consistent_pair[{number}]",
                        ],
                    ),
                    gate(
                        evidence,
                        "真实四指数、多股、三复权与分钟",
                        module,
                        [
                            *[
                                f"test_real_frozen_independent_indices_multi_stock_default_oracle[{s}-{number}]"
                                for s in ("SH:000001", "SZ:399001", "SH:000300", "SZ:399006")
                            ],
                            *[
                                f"test_real_frozen_adjustments_and_minute_exact_alignment[{a}-{number}]"
                                for a in ("NONE", "QFQ", "HFQ")
                            ],
                        ],
                    ),
                    gate(
                        evidence,
                        "取数隔离、原档及旧配置兼容",
                        module,
                        [
                            "test_series_pool_fetch_once_archive_and_missing_index_does_not_hide_other_factors",
                            "test_normal_factor_does_not_fetch_benchmark_and_invalid_choice_is_rejected",
                            "test_old_archive_migration_is_explicit_and_new_config_cannot_change_index",
                            "test_pool_shared_index_snapshot_and_reject_mixed_versions_in_archive_and_recompute",
                        ],
                    ),
                ]
            if number == 1:
                checks.append(
                    gate(
                        evidence,
                        "精确比例并列不得制造相关",
                        "tests.unit.test_alpha101_second",
                        [
                            "test_second_proportional_volume_and_return_ties_do_not_create_correlation"
                        ],
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
