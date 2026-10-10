"""Versioned mainland cash-equity calendar; unknown years never imply holidays known.

Annual exchange notices (not civil-service make-up working days):
2020 https://www.sse.com.cn/disclosure/announcement/general/c/c_20191220_4969627.shtml
2020 amendment https://www.sse.com.cn/disclosure/announcement/general/c/c_20200127_4991582.shtml
2021 https://www.sse.com.cn/disclosure/announcement/general/c/c_20201224_5286949.shtml
2022 https://www.sse.com.cn/disclosure/announcement/general/c/c_20211220_5662606.shtml
2023 https://www.sse.com.cn/disclosure/announcement/general/c/c_20221227_5714458.shtml
2024 https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml
2025 https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml
2026 https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml
"""

from datetime import date, timedelta

VERSION = "sse-cash-2020-2026-v2"
HOLIDAY_RANGES = {
    2020: [
        ("01-01", "01-01"),
        # Jan 27 emergency notice supersedes the original Jan 31 reopening.
        ("01-24", "02-02"),
        ("04-04", "04-06"),
        ("05-01", "05-05"),
        ("06-25", "06-27"),
        ("10-01", "10-08"),
    ],
    2021: [
        ("01-01", "01-03"),
        ("02-11", "02-17"),
        ("04-03", "04-05"),
        ("05-01", "05-05"),
        ("06-12", "06-14"),
        ("09-19", "09-21"),
        ("10-01", "10-07"),
    ],
    2022: [
        ("01-01", "01-03"),
        ("01-31", "02-06"),
        ("04-03", "04-05"),
        ("04-30", "05-04"),
        ("06-03", "06-05"),
        ("09-10", "09-12"),
        ("10-01", "10-07"),
    ],
    2023: [
        ("01-01", "01-02"),
        ("01-21", "01-27"),
        ("04-05", "04-05"),
        ("04-29", "05-03"),
        ("06-22", "06-24"),
        ("09-29", "10-06"),
    ],
    2024: [
        ("01-01", "01-01"),
        ("02-09", "02-17"),
        ("04-04", "04-06"),
        ("05-01", "05-05"),
        ("06-10", "06-10"),
        ("09-15", "09-17"),
        ("10-01", "10-07"),
    ],
    2025: [
        ("01-01", "01-01"),
        ("01-28", "02-04"),
        ("04-04", "04-06"),
        ("05-01", "05-05"),
        ("05-31", "06-02"),
        ("10-01", "10-08"),
    ],
    2026: [
        ("01-01", "01-03"),
        ("02-15", "02-23"),
        ("04-04", "04-06"),
        ("05-01", "05-05"),
        ("06-19", "06-21"),
        ("09-25", "09-27"),
        ("10-01", "10-07"),
    ],
}

# Keep the exact covered years, rather than claiming any gaps are verified.
COVERAGE_LABEL = "、".join(str(year) for year in sorted(HOLIDAY_RANGES))


def is_session(day: date) -> bool | None:
    if day.year not in HOLIDAY_RANGES:
        return None
    return day.weekday() < 5 and not any(
        date.fromisoformat(f"{day.year}-{start}") <= day <= date.fromisoformat(f"{day.year}-{end}")
        for start, end in HOLIDAY_RANGES[day.year]
    )


def last_session(start: date, end: date) -> date | None:
    """None means unknown coverage OR no session; never roll into another period."""
    if any(year not in HOLIDAY_RANGES for year in range(start.year, end.year + 1)):
        return None
    day = end
    while day >= start:
        if is_session(day):
            return day
        day -= timedelta(days=1)
    return None


def missing_sessions(start: date, end: date, observed: set[date]) -> list[str]:
    # Missing does not imply suspension or a feed outage: those require separate evidence.
    out = []
    day = start
    while day <= end:
        if is_session(day) is True and day not in observed:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out
