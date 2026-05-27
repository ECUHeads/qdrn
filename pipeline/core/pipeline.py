"""
Data Pipeline Orchestrator — Main ETL execution engine.

Coordinates Extract → Transform → Load phases with Dependency Injection,
event emission, timing metrics, and comprehensive error handling.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd

from pipeline.config import PipelineConfig
from pipeline.core.pipeline_result import PipelineResult
from pipeline.database.connection import DatabaseConnection
from pipeline.database.repository import AuditLogRepository, PipelineRunRepository
from pipeline.errors import PipelineError
from pipeline.events.bus import ObserverBus
from pipeline.extract.sources.base import AbstractDataSource
from pipeline.load.sinks.base import AbstractSink, LoadResult
from pipeline.logging import get_logger
from pipeline.transform.base import AbstractTransformer


class DataPipeline:
    """Main pipeline orchestrator with Dependency Injection.

    All dependencies are injected through the constructor, enabling
    testability and loose coupling between layers.
    """

    def __init__(
        self,
        source: AbstractDataSource,
        transformer: AbstractTransformer,
        sink: AbstractSink,
        observer_bus: ObserverBus,
        db_connection: Optional[DatabaseConnection] = None,
    ) -> None:
        self._source = source
        self._transformer = transformer
        self._sink = sink
        self._observer_bus = observer_bus
        self._db = db_connection
        self.logger = get_logger(__name__, component="DataPipeline")

    @property
    def db_connection(self) -> Optional[DatabaseConnection]:
        """Public accessor for the database connection."""
        return self._db

    def run(
        self,
        tickers: list[str],
        start: datetime,
        end: datetime,
        partition_key: Optional[str] = None,
    ) -> PipelineResult:
        """Execute the full ETL pipeline.

        Args:
            tickers: List of ticker symbols to extract.
            start: Start date for data extraction.
            end: End date for data extraction.
            partition_key: Optional key for organizing output data.

        Returns:
            PipelineResult with metrics and status.

        Raises:
            PipelineError: If any phase fails.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        partition_key = partition_key or f"{start.date()}_{end.date()}"
        start_time = time.monotonic()

        self._observer_bus.emit("PIPELINE_STARTED", {
            "run_id": run_id,
            "tickers": tickers,
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

        # Create pipeline run record in DB
        run_repo: Optional[PipelineRunRepository] = None
        if self._db:
            run_repo = PipelineRunRepository(self._db)
            run_repo.create(
                run_id=run_id,
                source_type=self._source.config.source_type,
                tickers=tickers,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                timeframe=self._source.config.timeframe,
            )

        raw_df: Optional[pd.DataFrame] = None
        processed_df: Optional[pd.DataFrame] = None

        try:
            # ── Phase 1: Extract ──────────────────────────────
            self.logger.info("Phase 1: Extract — %d tickers", len(tickers))
            t0 = time.monotonic()
            raw_df = self._source.extract(tickers, start, end)
            extract_ms = (time.monotonic() - t0) * 1000
            self.logger.info("Extracted %d rows in %.0fms", len(raw_df), extract_ms)

            # ── Phase 2: Transform ────────────────────────────
            self.logger.info("Phase 2: Transform")
            t0 = time.monotonic()
            processed_df = self._transformer.transform(raw_df)
            transform_ms = (time.monotonic() - t0) * 1000
            self.logger.info(
                "Transformed to %d rows (%d columns) in %.0fms",
                len(processed_df),
                len(processed_df.columns),
                transform_ms,
            )

            # ── Phase 3: Load ─────────────────────────────────
            self.logger.info("Phase 3: Load — partition=%s", partition_key)
            t0 = time.monotonic()
            load_result = self._sink.load(processed_df, partition_key)
            load_ms = (time.monotonic() - t0) * 1000
            self.logger.info(
                "Loaded %d rows (%d bytes) in %.0fms",
                load_result.rows_written,
                load_result.bytes_written,
                load_ms,
            )

            # ── Success ───────────────────────────────────────
            total_ms = (time.monotonic() - start_time) * 1000

            pipeline_result = PipelineResult(
                run_id=run_id,
                status="completed",
                rows_extracted=len(raw_df),
                rows_transformed=len(processed_df),
                rows_loaded=load_result.rows_written,
                bytes_written=load_result.bytes_written,
                extract_ms=extract_ms,
                transform_ms=transform_ms,
                load_ms=load_ms,
                total_ms=total_ms,
            )

            if run_repo:
                run_repo.update_status(
                    run_id,
                    "completed",
                    rows_extracted=len(raw_df),
                    rows_transformed=len(processed_df),
                    rows_loaded=load_result.rows_written,
                    bytes_written=load_result.bytes_written,
                    duration_ms=total_ms,
                )

            self._observer_bus.emit("PIPELINE_COMPLETED", {
                "run_id": run_id,
                "total_duration_ms": total_ms,
                "status": "success",
            })

            return pipeline_result

        except Exception as exc:
            total_ms = (time.monotonic() - start_time) * 1000

            pipeline_result = PipelineResult(
                run_id=run_id,
                status="failed",
                rows_extracted=len(raw_df) if raw_df is not None else 0,
                rows_transformed=len(processed_df) if processed_df is not None else 0,
                error=str(exc),
                total_ms=total_ms,
            )

            if run_repo:
                run_repo.update_status(
                    run_id,
                    "failed",
                    error_message=str(exc),
                    duration_ms=total_ms,
                )

            # Audit log
            if self._db:
                audit = AuditLogRepository(self._db)
                audit.log(
                    action="pipeline_failed",
                    entity_type="pipeline_run",
                    entity_id=None,
                    details={"run_id": run_id, "error": str(exc)},
                )

            self._observer_bus.emit("PIPELINE_FAILED", {
                "run_id": run_id,
                "total_duration_ms": total_ms,
                "error": str(exc),
            })

            raise PipelineError(f"Pipeline execution failed: {exc}") from exc

        finally:
            self._sink.close()
