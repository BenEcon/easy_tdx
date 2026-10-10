"""Rolling FF3 residual energy. Independent implementation, no data fetching.

Use an intercept and the current in-sample residual from each complete rolling
regression, followed by normalized exponential age weights. Decimal arithmetic
avoids price-return cancellation; normalized SVD only decides conditioning.
"""

from collections import deque
from decimal import Decimal, localcontext

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint

VERSION = "ff3-residual-energy-v1"
RANK_TOLERANCE = 1e-12


def _residual(rows: list[list[Decimal]]) -> Decimal | None:
    n = len(rows)
    means = [sum((r[j] for r in rows), Decimal(0)) / n for j in range(4)]
    centered = [[r[j] - means[j] for j in range(4)] for r in rows]
    scales = [max(abs(r[j]) for r in centered) for j in range(1, 4)]
    if any(s == 0 for s in scales):
        return None
    x = [[r[j + 1] / scales[j] for j in range(3)] for r in centered]
    singular = np.linalg.svd(np.asarray(x, dtype=float), compute_uv=False)
    if singular[-1] <= singular[0] * RANK_TOLERANCE:
        return None  # No ridge, dropped regressor or pseudoinverse substitution.
    # Three centered normal equations (intercept is already removed). Their
    # conditioning is bounded above before solving at 80-digit precision.
    matrix = [
        [sum((r[j] * r[k] for r in x), Decimal(0)) for k in range(3)]
        + [sum((x[i][j] * centered[i][0] for i in range(n)), Decimal(0))]
        for j in range(3)
    ]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda i: abs(matrix[i][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        if not divisor:
            return None
        matrix[column] = [v / divisor for v in matrix[column]]
        for i in range(3):
            if i != column:
                multiplier = matrix[i][column]
                matrix[i] = [a - multiplier * b for a, b in zip(matrix[i], matrix[column])]
    return centered[-1][0] - sum((x[-1][j] * matrix[j][-1] for j in range(3)), Decimal(0))


def residual_energy(data: pd.DataFrame, regression: int = 60, smoothing: int = 20) -> pd.Series:
    """Return one value per original row; invalid windows remain missing."""
    if (
        type(regression) is not int
        or type(smoothing) is not int
        or regression < 5
        or smoothing < 1
        or regression + smoothing > 600
    ):
        raise ValueError("风险回归窗口至少5，平滑至少1，合计不超过600根")
    keys = ["close", "risk_mkt", "risk_smb", "risk_hml"]
    if any(k not in data for k in keys) or len(data) > 800:
        raise ValueError("风险残差输入缺失或超出800根上限")
    values = data[keys].to_numpy(dtype=float)
    out = np.full(len(data), np.nan)
    history: deque[list[Decimal]] = deque(maxlen=regression)
    squares: deque[Decimal] = deque(maxlen=smoothing)
    previous: Decimal | None = None
    with localcontext() as ctx:
        ctx.prec = 80
        weights = [Decimal("0.9") ** i for i in reversed(range(smoothing))]
        denominator = sum(weights, Decimal(0))
        for i, row in enumerate(values):
            computation_checkpoint()
            if not np.isfinite(row[0]) or row[0] <= 0:
                previous = None
                history.clear()
                squares.clear()
                continue
            price = Decimal(str(row[0]))
            if previous is None or not np.isfinite(row[1:]).all():
                previous = price
                history.clear()
                squares.clear()
                continue
            history.append([price / previous - 1] + [Decimal(str(v)) for v in row[1:]])
            previous = price
            if len(history) < regression:
                continue
            residual = _residual(list(history))
            if residual is None:
                squares.clear()
                continue
            squares.append(residual * residual)
            if len(squares) == smoothing:
                value = sum((s * w for s, w in zip(squares, weights)), Decimal(0)) / denominator
                converted = float(value)
                if np.isfinite(converted) and (converted != 0 or value == 0):
                    out[i] = converted
    return pd.Series(out, index=data.index)
