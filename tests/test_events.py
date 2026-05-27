"""Tests for Observer Bus and event system."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pipeline.events.bus import (
    AlertObserver,
    LoggingObserver,
    MetricsObserver,
    ObserverBus,
)


class TestObserverBus:
    def test_subscribe_and_emit(self) -> None:
        bus = ObserverBus()
        mock_observer = MagicMock()
        bus.subscribe("TEST_EVENT", mock_observer)

        bus.emit("TEST_EVENT", {"key": "value"})
        mock_observer.on_event.assert_called_once_with("TEST_EVENT", {"key": "value"})

    def test_multiple_observers(self) -> None:
        bus = ObserverBus()
        obs1 = MagicMock()
        obs2 = MagicMock()
        bus.subscribe("EVENT", obs1)
        bus.subscribe("EVENT", obs2)

        bus.emit("EVENT", {"data": 1})
        assert obs1.on_event.call_count == 1
        assert obs2.on_event.call_count == 1

    def test_unsubscribe(self) -> None:
        bus = ObserverBus()
        mock_observer = MagicMock()
        bus.subscribe("EVT", mock_observer)
        bus.unsubscribe("EVT", mock_observer)

        bus.emit("EVT", {})
        mock_observer.on_event.assert_not_called()

    def test_emit_unknown_event(self) -> None:
        bus = ObserverBus()
        mock_observer = MagicMock()
        bus.subscribe("OTHER", mock_observer)

        bus.emit("UNKNOWN", {})
        mock_observer.on_event.assert_not_called()

    def test_observer_error_does_not_crash(self) -> None:
        bus = ObserverBus()
        bad_observer = MagicMock(side_effect=RuntimeError("crash"))
        good_observer = MagicMock()

        bus.subscribe("EVT", bad_observer)
        bus.subscribe("EVT", good_observer)

        bus.emit("EVT", {})  # Should not raise
        good_observer.on_event.assert_called_once()

    def test_subscriber_count(self) -> None:
        bus = ObserverBus()
        obs1 = MagicMock()
        obs2 = MagicMock()
        bus.subscribe("A", obs1)
        bus.subscribe("B", obs2)
        assert bus.subscriber_count == 2


class TestLoggingObserver:
    def test_on_event_logs(self) -> None:
        import logging
        mock_logger = MagicMock()
        observer = LoggingObserver(logger=mock_logger)
        observer.on_event("TEST", {"x": 1})
        mock_logger.info.assert_called_once()


class TestMetricsObserver:
    def test_collects_metrics(self) -> None:
        observer = MetricsObserver()
        observer.on_event("METRIC", {"value": 10})
        observer.on_event("METRIC", {"value": 20})

        metrics = observer.get_metrics("METRIC")
        assert len(metrics) == 2
        assert metrics[0]["value"] == 10


class TestAlertObserver:
    def test_alerts_on_failure(self) -> None:
        import logging
        mock_logger = MagicMock()
        observer = AlertObserver(logger=mock_logger)

        observer.on_event("PIPELINE_FAILED", {"error": "boom"})
        mock_logger.warning.assert_called_once()

    def test_no_alert_on_success(self) -> None:
        import logging
        mock_logger = MagicMock()
        observer = AlertObserver(logger=mock_logger)

        observer.on_event("PIPELINE_COMPLETED", {"status": "ok"})
        mock_logger.warning.assert_not_called()
