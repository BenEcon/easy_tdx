"""Descriptive research contracts, separate from strict trading structures."""

from typing import Literal, TypedDict


class PairPositionCounts(TypedDict, total=False):
    above_ma5_bars: int
    above_ma10_bars: int


class PairContext(PairPositionCounts):
    fast: float | None
    slow: float | None
    state: str
    description: str
    gap: float | None
    relative_gap: float | None
    fast_slope: float | None
    slow_slope: float | None
    gap_change: float | None
    directions: str
    position_bars: int


class Arrangement(TypedDict):
    to: int | None
    reason: str
    complete: bool


class IndicatorEvent(TypedDict):
    index: int
    date: str
    key: str
    direction: int
    label: str
    active: bool
    invalidated_at: str | None
    bars_ago: int


class PriceLeg(TypedDict):
    direction: str
    start_date: str
    end_date: str
    start_price: float
    end_price: float


class StrictPen(PriceLeg):
    locked: bool
    confirmed_date: str | None


class DirectionEvent(TypedDict):
    date: str
    state: str
    description: str
    anchor_date: str | None
    known_date: str | None


class DirectionHistory(TypedDict, total=False):
    history: list[DirectionEvent]


class PenObservation(DirectionHistory):
    strict: StrictPen | None
    state: Literal["insufficient", "invalidated", "waiting", "formed", "fractal_waiting"]
    direction: str | None
    description: str
    anchor_date: str | None
    anchor_price: float | None
    known_date: str | None
    projection: PriceLeg | None
    invalidation: str
    confirmation: str


class RecentContext(TypedDict):
    overall: str
    tail: str
    structure: str
    change_pct: float | None
    high: float
    low: float
    max_close_drawdown_pct: float | None
    first_close: float
    last_close: float
    summary: str
    method: str


class CoordinationComponent(TypedDict):
    key: str
    label: str
    supported: bool
    date: str | None
    description: str
