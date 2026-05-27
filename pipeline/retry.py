"""
Retry Mechanism with Exponential Backoff.

Provides a reusable retry wrapper with configurable max attempts,
exponential backoff delays, and jitter to prevent thundering herd.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Tuple, Type


logger = logging.getLogger(__name__)


class RetryMechanism:
    """Execute a callable with exponential backoff retry on failure."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 2.0,
        max_delay: float = 60.0,
        retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retryable_exceptions = retryable_exceptions

    def execute(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute *func* with retry logic.

        Raises:
            RetryExhaustedError: When all retry attempts are exhausted.
        """
        from pipeline.errors import RetryExhaustedError  # noqa: PLC2701

        last_exception: Exception | None = None
        func_name = getattr(func, "__name__", repr(func))

        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except self.retryable_exceptions as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = min(
                        self.base_delay * (2**attempt) + random.uniform(0, 1),
                        self.max_delay,
                    )
                    logger.warning(
                        "Retry attempt %d/%d for %s after %.1fs: %s",
                        attempt + 1,
                        self.max_retries,
                        func_name,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                else:
                    raise RetryExhaustedError(
                        message=f"Failed after {self.max_retries} retries: {exc}",
                        attempts=self.max_retries,
                        last_exception=exc,
                    ) from exc

        # Fallback (should not reach here, but satisfies type checker)
        if last_exception:
            raise last_exception
