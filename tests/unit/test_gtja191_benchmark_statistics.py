"""Independent least-squares and literal rolling-expression oracles."""

import copy
import hashlib
import json
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from easy_tdx.factor import get_factor
from easy_tdx.factor.benchmark import attach_benchmark
from easy_tdx.factor.catalog import describe_factor
from easy_tdx.factor.configuration import configure_factor
from tests.unit.test_gtja191_benchmark import pair, real_equity, real_index


def independent(frame, number, window):
    c = frame.close.to_numpy()
    b = frame.benchmark_close.to_numpy()
    out = np.full(len(c), np.nan)
    if number == 149:
        for end in range(len(c)):
            invalid = np.flatnonzero(
                ~np.isfinite(c[: end + 1])
                | ~np.isfinite(b[: end + 1])
                | (c[: end + 1] <= 0)
                | (b[: end + 1] <= 0)
            )
            start = int(invalid[-1] + 1) if len(invalid) else 0
            ids = [j for j in range(start + 1, end + 1) if b[j] < b[j - 1]][-window:]
            if len(ids) != window:
                continue
            x = np.array([b[j] / b[j - 1] - 1 for j in ids])
            y = np.array([c[j] / c[j - 1] - 1 for j in ids])
            if np.ptp(x) == 0:
                continue
            out[end] = np.linalg.lstsq(np.column_stack((np.ones(window), x)), y, rcond=None)[0][1]
        return out
    with localcontext() as ctx:
        ctx.prec = 70
        for end in range(2 * window - 1, len(c)):
            start = end - 2 * window + 1
            if not all(
                np.isfinite(v) and v > 0
                for values in (c[start : end + 1], b[start : end + 1])
                for v in values
            ):
                continue
            terms = []
            for j in range(end - window + 1, end + 1):
                returns = [
                    Decimal(str(c[k])) / Decimal(str(c[k - 1])) - 1
                    for k in range(j - window + 1, j + 1)
                ]
                deviation = (
                    Decimal(str(b[j]))
                    - sum(Decimal(str(x)) for x in b[j - window + 1 : j + 1]) / window
                )
                terms.append((returns[-1] - sum(returns) / window - deviation**2, deviation**3))
            den = sum(t[1] for t in terms)
            if den:
                out[end] = float(sum(t[0] for t in terms) / den)
    return out


@pytest.mark.parametrize(
    "number,window", [(149, 2), (149, 7), (149, 252), (181, 1), (181, 3), (181, 20)]
)
def test_default_custom_independent_formula_and_prefix(number, window):
    stock, index = pair(length=620 if window == 252 else 100)
    factor = configure_factor(f"gtja191_{number:03}", {"window": window})
    frame = attach_benchmark(stock, index, "SH:000001")
    original = copy.deepcopy(frame)
    value = factor.compute(frame)
    np.testing.assert_allclose(
        value, independent(frame, number, window), rtol=1e-8, atol=1e-12, equal_nan=True
    )
    if not (number == 181 and window == 1):
        assert value.notna().any()
    prefix = len(frame) - 9
    pd.testing.assert_series_equal(
        value.iloc[:prefix],
        factor.compute(attach_benchmark(stock.iloc[:prefix], index.iloc[:prefix], "SH:000001")),
    )
    pd.testing.assert_frame_equal(frame, original)


def test_filtered_beta_counts_selected_samples_holds_non_down_and_resets_gap():
    stock, index = pair(length=10)
    stock["close"] = [100, 80, 90, 81, 90, 108, 100, 80, 72, 80]
    index["close"] = [100, 90, 100, 80, 100, 90, 100, 80, 60, 80]
    frame = attach_benchmark(stock, index, "SH:000001")
    factor = configure_factor("gtja191_149", {"window": 2})
    values = factor.compute(frame)
    assert values.iloc[:3].isna().all()
    assert values.iloc[3] == pytest.approx(-1)
    assert values.iloc[4] == values.iloc[3]
    np.testing.assert_allclose(values, independent(frame, 149, 2), atol=1e-12, equal_nan=True)
    stock.loc[5, "close"] = np.nan
    broken = attach_benchmark(stock, index, "SH:000001")
    after = factor.compute(broken)
    assert after.iloc[5:8].isna().all() and pd.notna(after.iloc[8])
    np.testing.assert_allclose(after, independent(broken, 149, 2), atol=1e-12, equal_nan=True)


@pytest.mark.parametrize("number", [149, 181])
def test_constant_invalid_missing_and_cancel(number, monkeypatch):
    stock, index = pair(length=80)
    factor = configure_factor(f"gtja191_{number:03}", {"window": 3})
    flat = index.copy()
    flat["close"] = 3000.0
    assert factor.compute(attach_benchmark(stock, flat, "SH:000001")).isna().all()
    for bad in [np.nan, 0.0, -1.0, np.inf]:
        altered = stock.copy()
        altered.loc[40, "close"] = bad
        frame = attach_benchmark(altered, index, "SH:000001")
        np.testing.assert_allclose(
            factor.compute(frame),
            independent(frame, number, 3),
            atol=1e-12,
            rtol=1e-8,
            equal_nan=True,
        )

    class Cancelled(BaseException):
        pass

    checkpoints = 0

    def cancel():
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == 3:
            raise Cancelled()

    monkeypatch.setattr(
        "easy_tdx.factor.builtin.benchmark_statistics.computation_checkpoint", cancel
    )
    with pytest.raises(Cancelled):
        factor.compute(attach_benchmark(stock, index, "SH:000001"))
    assert checkpoints == 3


def test_signed_cubic_exact_zero_and_old_outlier_leaves_window():
    stock, index = pair(length=50)
    stock["close"] = 10.0
    index["close"] = [100.0, 102.0, 100.0, 102.0] * 12 + [100.0, 102.0]
    factor = configure_factor("gtja191_181", {"window": 2})
    assert factor.compute(attach_benchmark(stock, index, "SH:000001")).isna().all()
    normal_stock, normal_index = pair(length=80)
    normal = attach_benchmark(normal_stock, normal_index, "SH:000001")
    normal_index.loc[4, "close"] = 1e150
    altered = attach_benchmark(normal_stock, normal_index, "SH:000001")
    pd.testing.assert_series_equal(
        factor.compute(normal).iloc[10:], factor.compute(altered).iloc[10:]
    )


@pytest.mark.parametrize("number", [149, 181])
@pytest.mark.parametrize("adjust", ["NONE", "QFQ", "HFQ"])
def test_real_multi_period_adjustments_and_independent_indices(number, adjust):
    from tests.unit.test_factor_data import frozen

    window = 20 if number == 181 else 30
    factor = configure_factor(f"gtja191_{number:03}", {"window": window})
    for period in ("DAILY", "MIN_30"):
        stock = real_equity(frozen(f"0-300750-{period}-{adjust}.json"))
        index = real_index("SH-000001-" + ("DAY" if period == "DAILY" else period) + ".json")
        frame = attach_benchmark(stock, index, "SH:000001")
        values = factor.compute(frame)
        np.testing.assert_allclose(
            values, independent(frame, number, window), rtol=1e-8, atol=1e-12, equal_nan=True
        )
        assert values.notna().any()


@pytest.mark.parametrize("number", [149, 181])
@pytest.mark.parametrize(
    "name", ["SZ-000001-stock.json", "SZ-300750-stock.json", "SH-600036-stock.json"]
)
def test_default_real_800_bars_multi_stock_independent_oracle(number, name):
    from easy_tdx.factor.snapshot import restore_input

    root = Path(__file__).parents[1] / "fixtures/factor_benchmark_long"
    hashes = dict(line.split()[::-1] for line in (root / "SHA256SUMS").read_text().splitlines())

    def load(filename):
        data = (root / filename).read_bytes()
        assert hashlib.sha256(data).hexdigest() == hashes[filename]
        return restore_input(json.loads(data)["snapshot"])

    stock, index = load(name), load("SH-000001-index.json")
    frame = attach_benchmark(stock, index, "SH:000001")
    factor = get_factor(f"gtja191_{number:03}")()
    values = factor.compute(frame)
    np.testing.assert_allclose(
        values,
        independent(frame, number, factor.spec.window),
        rtol=1e-8,
        atol=1e-12,
        equal_nan=True,
    )
    assert values.notna().sum() > 100


def test_filtered_sample_units_and_insufficient_default_history_are_explicit():
    meta = describe_factor(get_factor("gtja191_149"))
    assert meta["parameters"]["window"]["unit"] == "selected_observations"
    assert "不是" in meta["formula"] and "最少" in meta["warmup_note"]
    stock, index = pair(length=320)
    assert (
        get_factor("gtja191_149")()
        .compute(attach_benchmark(stock, index, "SH:000001"))
        .isna()
        .all()
    )
