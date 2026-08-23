"""Circuit breaker contracts."""

import time

import pytest

from free_claude_code.core.circuit_breaker import (
    CircuitBreakerRegistry,
    CircuitState,
    ProviderCircuitBreaker,
)
from free_claude_code.core.failures import ExecutionFailure, FailureKind


def _failure(kind: FailureKind) -> ExecutionFailure:
    return ExecutionFailure(kind=kind, status_code=503, message="test", retryable=True)


class TestProviderCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = ProviderCircuitBreaker("test", threshold=3, cooldown_seconds=60)
        assert cb.state == CircuitState.CLOSED
        assert cb.is_healthy is True

    def test_trips_after_threshold(self) -> None:
        cb = ProviderCircuitBreaker("test", threshold=3, cooldown_seconds=60)
        for _ in range(3):
            cb.record_failure(_failure(FailureKind.RATE_LIMIT))
        assert cb.state == CircuitState.OPEN
        assert cb.is_healthy is False

    def test_below_threshold_stays_closed(self) -> None:
        cb = ProviderCircuitBreaker("test", threshold=3, cooldown_seconds=60)
        for _ in range(2):
            cb.record_failure(_failure(FailureKind.RATE_LIMIT))
        assert cb.state == CircuitState.CLOSED
        assert cb.is_healthy is True

    def test_non_trip_kind_ignored(self) -> None:
        cb = ProviderCircuitBreaker("test", threshold=3, cooldown_seconds=60)
        for _ in range(5):
            cb.record_failure(_failure(FailureKind.INVALID_REQUEST))
        assert cb.state == CircuitState.CLOSED

    def test_cooldown_transitions_to_half_open(self) -> None:
        cb = ProviderCircuitBreaker("test", threshold=2, cooldown_seconds=0.1)
        cb.record_failure(_failure(FailureKind.OVERLOADED))
        cb.record_failure(_failure(FailureKind.OVERLOADED))
        assert cb._state == CircuitState.OPEN
        # Wait for cooldown to expire so .state transitions to HALF_OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.is_healthy is True

    def test_successful_probe_closes_circuit(self) -> None:
        cb = ProviderCircuitBreaker("test", threshold=2, cooldown_seconds=0.1)
        cb.record_failure(_failure(FailureKind.UPSTREAM))
        cb.record_failure(_failure(FailureKind.UPSTREAM))
        assert cb._state == CircuitState.OPEN
        # Wait for cooldown so .state transitions to HALF_OPEN
        time.sleep(0.15)
        _ = cb.state
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.is_healthy is True

    def test_failed_probe_reopens_circuit(self) -> None:
        cb = ProviderCircuitBreaker("test", threshold=2, cooldown_seconds=0.1)
        cb.record_failure(_failure(FailureKind.UNAVAILABLE))
        cb.record_failure(_failure(FailureKind.UNAVAILABLE))
        time.sleep(0.15)
        _ = cb.state  # HALF_OPEN
        cb.record_failure(_failure(FailureKind.UNAVAILABLE))
        assert cb._state == CircuitState.OPEN

    def test_old_failures_pruned_by_cooldown(self) -> None:
        """Failures outside the cooldown window are pruned, preventing false trips."""
        cb = ProviderCircuitBreaker("test", threshold=3, cooldown_seconds=0.1)
        cb.record_failure(_failure(FailureKind.RATE_LIMIT))
        cb.record_failure(_failure(FailureKind.RATE_LIMIT))
        # Wait for the failures to age out of the sliding window
        time.sleep(0.15)
        # Third failure should not trip — old failures were pruned
        cb.record_failure(_failure(FailureKind.RATE_LIMIT))
        assert cb.state == CircuitState.CLOSED

    def test_rejects_invalid_threshold(self) -> None:
        with pytest.raises(ValueError, match="threshold must be >= 1"):
            ProviderCircuitBreaker("test", threshold=0)

    def test_rejects_invalid_cooldown(self) -> None:
        with pytest.raises(ValueError, match="cooldown_seconds must be >= 0"):
            ProviderCircuitBreaker("test", threshold=1, cooldown_seconds=-1)


class TestCircuitBreakerRegistry:
    def test_creates_breaker_on_first_access(self) -> None:
        reg = CircuitBreakerRegistry(threshold=3, cooldown_seconds=60)
        cb = reg.get("provider_a")
        assert cb.state == CircuitState.CLOSED

    def test_returns_same_breaker_for_same_provider(self) -> None:
        reg = CircuitBreakerRegistry(threshold=3, cooldown_seconds=60)
        cb1 = reg.get("provider_a")
        cb2 = reg.get("provider_a")
        assert cb1 is cb2

    def test_independent_breakers_per_provider(self) -> None:
        reg = CircuitBreakerRegistry(threshold=2, cooldown_seconds=60)
        cb_a = reg.get("provider_a")
        cb_b = reg.get("provider_b")
        cb_a.record_failure(_failure(FailureKind.RATE_LIMIT))
        cb_a.record_failure(_failure(FailureKind.RATE_LIMIT))
        assert cb_a.state == CircuitState.OPEN
        assert cb_b.state == CircuitState.CLOSED

    def test_status_snapshot(self) -> None:
        reg = CircuitBreakerRegistry(threshold=3, cooldown_seconds=60)
        reg.get("p1")
        reg.get("p2").record_failure(_failure(FailureKind.UPSTREAM))
        snap = reg.status_snapshot()
        assert "p1" in snap
        assert "p2" in snap
        assert snap["p1"]["state"] == "closed"
        assert snap["p2"]["recent_failures"] == 1
