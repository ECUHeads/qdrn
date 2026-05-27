"""
Source Factory — Registry-based factory for data source instantiation.

Uses the Factory pattern with a decorator-based registration system
to create appropriate source instances from configuration.
"""

from __future__ import annotations

from typing import Callable, Dict, Type

from pipeline.config import SourceConfig
from pipeline.errors import SourceNotFoundError
from pipeline.extract.sources.base import AbstractDataSource


class SourceFactory:
    """Registry-based factory for creating data source instances."""

    _registry: Dict[str, Type[AbstractDataSource]] = {}

    @classmethod
    def register(cls, name: str) -> Callable:
        """Decorator to register a data source class by name."""
        def decorator(source_cls: Type[AbstractDataSource]) -> Type[AbstractDataSource]:
            cls._registry[name] = source_cls
            return source_cls
        return decorator

    @classmethod
    def create_source(
        cls,
        config: SourceConfig,
        observer_bus: Optional["ObserverBus"] = None,
        proxy: Optional[str] = None,
    ) -> AbstractDataSource:
        """Create a data source instance from configuration.

        Args:
            config: Source configuration.
            observer_bus: Optional event bus for observability.
            proxy: Optional proxy URL for blocked regions.
        """
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from pipeline.events.bus import ObserverBus  # noqa: F811

        source_cls = cls._registry.get(config.source_type)
        if source_cls is None:
            raise SourceNotFoundError(
                config.source_type,
                available=list(cls._registry.keys()),
            )
        return source_cls(config=config, observer_bus=observer_bus, proxy=proxy)

    @classmethod
    def get_available_sources(cls) -> list[str]:
        """Return list of registered source type names."""
        return list(cls._registry.keys())
