"""单元测试：实时数据推送引擎."""

from __future__ import annotations

import asyncio

import pytest

from easy_tdx.realtime.engine import (
    EventBus,
    EventType,
    MarketEvent,
    RealtimeStrategy,
)


class TestMarketEvent:
    """测试行情事件."""

    def test_event_creation(self) -> None:
        """创建事件应正确设置字段."""
        event = MarketEvent(
            event_type=EventType.TICK,
            code="000001",
            market="SZ",
            price=10.5,
            volume=1000,
            timestamp=1700000000.0,
        )

        assert event.event_type == EventType.TICK
        assert event.code == "000001"
        assert event.market == "SZ"
        assert event.price == 10.5

    def test_event_default_values(self) -> None:
        """默认值应为零和空字典."""
        event = MarketEvent(
            event_type=EventType.BAR,
            code="600000",
            market="SH",
        )

        assert event.price == 0.0
        assert event.volume == 0.0
        assert event.data == {}


class TestEventBus:
    """测试事件总线."""

    def test_subscribe_and_count(self) -> None:
        """订阅后计数应正确."""
        bus = EventBus()
        bus.subscribe("SZ000001", lambda e: None)
        bus.subscribe("SZ000001", lambda e: None)
        bus.subscribe("SH600000", lambda e: None)

        assert bus.subscriber_count == 3

    def test_subscribe_global(self) -> None:
        """全局订阅应被计入."""
        bus = EventBus()
        bus.subscribe_all(lambda e: None)

        assert bus.subscriber_count == 1

    def test_unsubscribe_global(self) -> None:
        """WebSocket 断开后应移除全局订阅，避免回调泄漏。"""
        bus = EventBus()
        handler = lambda e: None  # noqa: E731
        bus.subscribe_all(handler)
        bus.unsubscribe_all(handler)

        assert bus.subscriber_count == 0

    def test_unsubscribe(self) -> None:
        """取消订阅后计数应减少."""
        bus = EventBus()
        handler = lambda e: None  # noqa: E731
        bus.subscribe("SZ000001", handler)
        bus.unsubscribe("SZ000001", handler)

        assert bus.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_publish_to_specific_subscriber(self) -> None:
        """发布事件应通知特定订阅者."""
        bus = EventBus()
        received: list[MarketEvent] = []

        async def handler(event: MarketEvent) -> None:
            received.append(event)

        bus.subscribe("SZ000001", handler)

        event = MarketEvent(
            event_type=EventType.TICK,
            code="000001",
            market="SZ",
            price=10.5,
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].price == 10.5

    @pytest.mark.asyncio
    async def test_publish_to_global_subscriber(self) -> None:
        """全局订阅者应收到所有事件."""
        bus = EventBus()
        received: list[MarketEvent] = []

        bus.subscribe_all(lambda e: received.append(e))

        event = MarketEvent(
            event_type=EventType.TICK,
            code="000001",
            market="SZ",
        )
        await bus.publish(event)

        assert len(received) == 1


class TestRealtimeStrategy:
    """测试实时策略基类."""

    def test_on_tick_default_does_nothing(self) -> None:
        """默认 on_tick 不应抛异常."""
        strategy = RealtimeStrategy()
        event = MarketEvent(
            event_type=EventType.TICK,
            code="000001",
            market="SZ",
        )
        strategy.on_tick(event)  # should not raise

    @pytest.mark.asyncio
    async def test_emit_signal_without_bus(self) -> None:
        """无 event_bus 时 emit_signal 不应抛异常."""
        strategy = RealtimeStrategy()
        event = MarketEvent(
            event_type=EventType.TICK,
            code="000001",
            market="SZ",
            price=10.0,
        )
        strategy.emit_signal("BUY", event)

    @pytest.mark.asyncio
    async def test_emit_signal_publishes_to_bus(self) -> None:
        """emit_signal 应发布 SIGNAL 类型事件."""
        bus = EventBus()
        received: list[MarketEvent] = []
        bus.subscribe("SZ000001", lambda e: received.append(e))

        strategy = RealtimeStrategy(event_bus=bus)
        event = MarketEvent(
            event_type=EventType.TICK,
            code="000001",
            market="SZ",
            price=10.0,
            timestamp=1700000000.0,
        )

        strategy.emit_signal("BUY", event)
        # Give the asyncio task time to run
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0].event_type == EventType.SIGNAL
        assert received[0].data["direction"] == "BUY"
