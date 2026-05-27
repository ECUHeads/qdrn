"""
Observer Bus — Publisher-Subscriber event system.

Implements the Observer pattern for decoupled event emission and handling.
All pipeline components emit events through this bus for monitoring,
logging, metrics collection, and alerting.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class PipelineObserver(Protocol):
    """Interface that all event observers must implement."""

    def on_event(self, event_type: str, payload: dict) -> None: ...


class ObserverBus:
    """Publisher-Subscriber event bus for pipeline observability."""

    def __init__(self) -> None:
        self._observers: Dict[str, List[PipelineObserver]] = {}
        self.logger = logging.getLogger(f"{__name__}.ObserverBus")

    def subscribe(self, event_type: str, observer: PipelineObserver) -> None:
        """Register an observer for a specific event type."""
        self._observers.setdefault(event_type, []).append(observer)
        self.logger.debug("Subscribed %s to %s", observer.__class__.__name__, event_type)

    def unsubscribe(self, event_type: str, observer: PipelineObserver) -> None:
        """Remove an observer from a specific event type."""
        observers = self._observers.get(event_type, [])
        if observer in observers:
            observers.remove(observer)
            self.logger.debug("Unsubscribed %s from %s", observer.__class__.__name__, event_type)

    def emit(self, event_type: str, payload: dict) -> None:
        """Emit an event to all registered observers."""
        for observer in self._observers.get(event_type, []):
            try:
                observer.on_event(event_type, payload)
            except Exception as exc:
                self.logger.error("Observer %s failed on %s: %s", observer.__class__.__name__, event_type, exc)

    @property
    def subscriber_count(self) -> int:
        """Total number of registered observers across all event types."""
        return sum(len(obs) for obs in self._observers.values())


# ---------------------------------------------------------------------------
# Built-in Observers
# ---------------------------------------------------------------------------

class LoggingObserver:
    """Observer that logs all events to the structured logger."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("PipelineEvents")

    def on_event(self, event_type: str, payload: dict) -> None:
        self.logger.info("Event[%s]: %s", event_type, payload)


class MetricsObserver:
    """Observer that collects metrics from pipeline events."""

    def __init__(self) -> None:
        self.metrics: Dict[str, list] = {}

    def on_event(self, event_type: str, payload: dict) -> None:
        self.metrics.setdefault(event_type, []).append(payload)

    def get_metrics(self, event_type: str) -> list:
        """Retrieve collected metrics for a specific event type."""
        return self.metrics.get(event_type, [])


class AlertObserver:
    """Observer that triggers alerts on error events."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("PipelineAlerts")

    def on_event(self, event_type: str, payload: dict) -> None:
        if "FAILED" in event_type or "ERROR" in event_type:
            self.logger.warning("ALERT %s: %s", event_type, payload)
