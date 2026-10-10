"""Calendar-period equity samples; closure carry is not a fabricated market bar."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.computation import computation_checkpoint
from easy_tdx.web.trading_calendar import is_session, last_session


def expand_closed_periods(
    dates: pd.DatetimeIndex,
    values: np.ndarray[Any, np.dtype[np.float64]],
    frequency: str,
) -> tuple[pd.DatetimeIndex, np.ndarray[Any, np.dtype[np.float64]], list[dict[str, Any]]]:
    """Fill only fully verified sessionless *interior* periods with prior equity.

    This engine has no off-bar deposits, financing accrual or corporate-action cash
    events. Carrying its prior equity through a verified exchange closure is thus
    an explicit valuation convention, not evidence of a quote or a filled order.
    Never fill a suspended/missing security's period which had exchange sessions.
    Unknown calendars, duplicate periods and reverse time fail closed. No trailing
    period is invented beyond the last observation in the supplied snapshot.
    """
    periods = dates.to_period(frequency)
    if len(periods) < 2:
        return dates, values, []
    differences = np.diff(periods.asi8)
    if np.any(differences <= 0):
        raise ValueError("绩效周期重复或缺失，未将跨周期收益当作单周期收益")
    if np.all(differences == 1):
        return dates, values, []
    stamps = [dates[0]]
    samples = [float(values[0])]
    carried: list[dict[str, Any]] = []
    for index in range(1, len(periods)):
        computation_checkpoint()
        if differences[index - 1] > 1:
            for period in pd.period_range(periods[index - 1] + 1, periods[index] - 1):
                computation_checkpoint()
                start, end = period.start_time.date(), period.end_time.date()
                if is_session(start) is None or is_session(end) is None:
                    raise ValueError("交易日历未覆盖缺失周期，不能将其判为整周期休市")
                if last_session(start, end) is not None:
                    raise ValueError("绩效周期重复或缺失，缺失周期有交易日，不能沿用估值补齐")
                stamp = period.end_time.normalize() + pd.Timedelta(hours=15)
                prior = float(values[index - 1])
                stamps.append(stamp)
                samples.append(prior)
                carried.append(
                    {
                        "period": str(period),
                        "datetime": stamp.isoformat(),
                        "source_time": dates[index - 1].isoformat(),
                        "valuation": prior if np.isfinite(prior) else None,
                        "reason": "交易所整周期休市，沿用前次估值；非行情或交易记录",
                    }
                )
        stamps.append(dates[index])
        samples.append(float(values[index]))
    return pd.DatetimeIndex(stamps), np.asarray(samples, dtype=float), carried
