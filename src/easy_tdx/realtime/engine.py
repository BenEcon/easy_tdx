"""实时数据推送引擎。

基于 asyncio 的事件驱动架构，支持：
- 行情订阅与推送
- 实时策略信号触发
- 多标的并发监控

.. note::

    ``EventBus`` 是纯发布/订阅管道，自身不会产生数据。要驱动
    :class:`RealtimeStrategy`，需要配合 :mod:`easy_tdx.realtime.feed` 的
    :class:`RealtimeDataFeed`（轮询 ``get_stock_quotes`` 快照）或自行实现
    调用 ``bus.publish`` 的数据源。通达信协议无服务端推送，本模块的「实时」
    是轮询快照近似（默认约 3 秒延迟）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(Enum):
    """事件类型。"""

    TICK = "tick"
    BAR = "bar"
    SIGNAL = "signal"
    ERROR = "error"


@dataclass
class MarketEvent:
    """行情事件。

    Attributes:
        event_type: 事件类型
        code: 股票代码（如 "000001"）
        market: 市场（如 "SZ"）
        price: 最新价格
        volume: 成交量
        timestamp: 事件时间戳
        data: 额外数据
    """

    event_type: EventType
    code: str
    market: str
    price: float = 0.0
    volume: float = 0.0
    timestamp: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)


# 回调函数类型
EventHandler = Callable[[MarketEvent], Any]


class EventBus:
    """异步事件总线。

    发布/订阅模式，支持多个订阅者监听行情事件。

    用法::

        bus = EventBus()
        bus.subscribe("SZ000001", on_tick)
        await bus.publish(event)
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._global_subscribers: list[EventHandler] = []

    def subscribe(self, symbol: str, handler: EventHandler) -> None:
        """订阅指定标的的事件。

        Args:
            symbol: 标的标识（如 "SZ000001"）
            handler: 事件处理回调
        """
        if symbol not in self._subscribers:
            self._subscribers[symbol] = []
        self._subscribers[symbol].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """订阅所有标的的事件。

        Args:
            handler: 事件处理回调
        """
        self._global_subscribers.append(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """取消一个全局订阅回调。"""
        self._global_subscribers = [h for h in self._global_subscribers if h != handler]

    def unsubscribe(self, symbol: str, handler: EventHandler) -> None:
        """取消订阅。

        Args:
            symbol: 标的标识
            handler: 要移除的回调
        """
        if symbol in self._subscribers:
            self._subscribers[symbol] = [h for h in self._subscribers[symbol] if h != handler]

    async def publish(self, event: MarketEvent) -> None:
        """发布事件到所有匹配的订阅者。

        Args:
            event: 行情事件
        """
        symbol = f"{event.market}{event.code}"

        # 通知特定标的的订阅者
        handlers = self._subscribers.get(symbol, [])
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Event handler error for %s", symbol)

        # 通知全局订阅者
        for handler in self._global_subscribers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Global event handler error")

    @property
    def subscriber_count(self) -> int:
        """当前订阅者总数。"""
        count = len(self._global_subscribers)
        for handlers in self._subscribers.values():
            count += len(handlers)
        return count


class RealtimeStrategy:
    """实时策略基类。

    用户子类实现 on_tick / on_bar 方法，在收到实时行情时
    自动触发，可通过 event_bus 发布交易信号。

    用法::

        class MyRealtimeStrategy(RealtimeStrategy):
            def on_tick(self, event: MarketEvent) -> None:
                if event.price > self.threshold:
                    self.emit_signal("BUY", event)

        strategy = MyRealtimeStrategy(threshold=10.5)
        bus = EventBus()
        bus.subscribe_all(strategy.on_tick)
    """

    def __init__(self, event_bus: EventBus | None = None, **kwargs: Any) -> None:
        """初始化实时策略。

        Args:
            event_bus: 事件总线（可选，用于发送信号）
            **kwargs: 用户自定义参数
        """
        self._event_bus = event_bus
        self._params = kwargs

    def on_tick(self, event: MarketEvent) -> None:
        """处理 tick 事件（用户实现）。

        Args:
            event: 行情事件
        """

    def on_bar(self, event: MarketEvent) -> None:
        """处理 bar 完成事件（用户实现）。

        Args:
            event: 行情事件
        """

    def emit_signal(
        self,
        direction: str,
        event: MarketEvent,
        size: float = 0,
        price: float | None = None,
    ) -> None:
        """发送交易信号事件。

        Args:
            direction: 交易方向 ("BUY" / "SELL")
            event: 触发信号的行情事件
            size: 交易数量（0 = 全仓）
            price: 信号价格（None = 市价）
        """
        if self._event_bus is None:
            logger.warning("No event bus configured, signal not sent")
            return

        signal_event = MarketEvent(
            event_type=EventType.SIGNAL,
            code=event.code,
            market=event.market,
            price=price or event.price,
            volume=size,
            timestamp=event.timestamp,
            data={"direction": direction},
        )
        # fire-and-forget signal publish
        asyncio.ensure_future(self._event_bus.publish(signal_event))
