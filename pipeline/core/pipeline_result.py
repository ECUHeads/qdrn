"""
Pipeline Result — Immutable dataclass for pipeline execution results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PipelineResult:
    """Immutable result of a pipeline execution."""

    run_id: str
    status: str  # "completed" | "failed"
    rows_extracted: int = 0
    rows_transformed: int = 0
    rows_loaded: int = 0
    bytes_written: int = 0
    extract_ms: float = 0.0
    transform_ms: float = 0.0
    load_ms: float = 0.0
    total_ms: float = 0.0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        """Check if pipeline completed successfully."""
        return self.status == "completed"

    def summary(self) -> str:
        """Human-readable summary string."""
        status_icon = "✅" if self.success else "❌"
        return (
            f"{status_icon} [{self.run_id}] {self.status.upper()} | "
            f"Extracted: {self.rows_extracted}, "
            f"Transformed: {self.rows_transformed}, "
            f"Loaded: {self.rows_loaded} rows, "
            f"Total: {self.total_ms:.0f}ms"
        )
