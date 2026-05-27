"""Extract layer — Data source abstractions and factory."""

from pipeline.extract.factory import SourceFactory
from pipeline.extract.sources.base import AbstractDataSource

__all__ = ["AbstractDataSource", "SourceFactory"]
