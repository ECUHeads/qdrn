"""
Parquet Sink — Writes processed data to Apache Parquet files.

Columnar storage format optimized for analytics and ML training workloads.
Supports partitioning by ticker and date with Snappy compression.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config import SinkConfig
from pipeline.events.bus import ObserverBus
from pipeline.load.sinks.base import AbstractSink, LoadResult


class ParquetSink(AbstractSink):
    """Write processed data to Apache Parquet files."""

    def load(self, df: pd.DataFrame, partition_key: str) -> LoadResult:
        """Write DataFrame to a Parquet file."""
        self._emit_event("LOAD_STARTED", {"sink_type": "parquet", "partition_key": partition_key})

        output_path = Path(self.config.output_path) / f"{partition_key}.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        table = pa.Table.from_pandas(df)
        pq.write_table(
            table,
            str(output_path),
            compression=self.config.compression,
        )

        bytes_written = output_path.stat().st_size
        result = LoadResult(
            rows_written=len(df),
            bytes_written=bytes_written,
            partition_key=partition_key,
        )

        self._emit_event("LOAD_COMPLETED", {
            "sink_type": "parquet",
            "rows_written": len(df),
            "bytes_written": bytes_written,
            "path": str(output_path),
        })

        self.logger.info(
            "Wrote %d rows (%d bytes) to %s",
            len(df),
            bytes_written,
            output_path,
        )
        return result

    def close(self) -> None:
        """No persistent connection to close."""
        pass
