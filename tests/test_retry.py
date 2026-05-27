"""Tests for retry mechanism."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from pipeline.errors import RetryExhaustedError
from pipeline.retry import RetryMechanism


class TestRetryMechanism:
    def test_success_first_try(self) -> None:
        mock_fn = MagicMock(return_value="ok")
        retry = RetryMechanism(max_retries=3, base_delay=0.01)
        result = retry.execute(mock_fn)
        assert result == "ok"
        assert mock_fn.call_count == 1

    def test_success_after_retry(self) -> None:
        mock_fn = MagicMock(side_effect=[ValueError("x"), ValueError("x"), "ok"])
        retry = RetryMechanism(max_retries=3, base_delay=0.01)
        result = retry.execute(mock_fn)
        assert result == "ok"
        assert mock_fn.call_count == 3

    def test_exhausted_retries(self) -> None:
        mock_fn = MagicMock(side_effect=ValueError("always fails"))
        retry = RetryMechanism(max_retries=2, base_delay=0.01)
        with pytest.raises(RetryExhaustedError) as exc_info:
            retry.execute(mock_fn)
        assert exc_info.value.attempts == 2
        assert mock_fn.call_count == 3  # initial + 2 retries

    def test_non_retryable_exception(self) -> None:
        mock_fn = MagicMock(side_effect=KeyError("not retryable"))
        retry = RetryMechanism(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ValueError,),
        )
        with pytest.raises(KeyError):
            retry.execute(mock_fn)
        assert mock_fn.call_count == 1

    def test_exponential_backoff(self) -> None:
        """Verify that delay increases exponentially."""
        mock_fn = MagicMock(side_effect=ValueError("fail"))
        delays = []

        original_sleep = time.sleep

        def fake_sleep(duration):
            delays.append(duration)

        with patch("time.sleep", fake_sleep):
            retry = RetryMechanism(max_retries=3, base_delay=1.0, max_delay=60.0)
            try:
                retry.execute(mock_fn)
            except RetryExhaustedError:
                pass

        assert len(delays) == 3
        assert delays[0] < delays[1] < delays[2]

    def test_max_delay_cap(self) -> None:
        mock_fn = MagicMock(side_effect=ValueError("fail"))
        delays = []

        def fake_sleep(duration):
            delays.append(duration)

        with patch("time.sleep", fake_sleep):
            retry = RetryMechanism(max_retries=10, base_delay=1.0, max_delay=5.0)
            try:
                retry.execute(mock_fn)
            except RetryExhaustedError:
                pass

        for delay in delays:
            assert delay <= 5.0 + 1  # max_delay + jitter
