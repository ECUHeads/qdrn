"""Event system — Observer pattern implementation."""

from pipeline.events.bus import ObserverBus, PipelineObserver

__all__ = ["ObserverBus", "PipelineObserver"]
