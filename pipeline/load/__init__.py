"""Load layer — Data sink abstractions and implementations."""

from pipeline.load.sinks.base import AbstractSink, LoadResult
from pipeline.load.sinks.parquet import ParquetSink
from pipeline.load.sinks.sqlite_sink import SQLiteSink

__all__ = ["AbstractSink", "LoadResult", "ParquetSink", "SQLiteSink"]
