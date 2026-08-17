"""Per-provider circuit breaker to short-circuit known-unhealthy providers."""

import time
from collections import deque
from enum import StrEnum

from loguru import logger

from free_claude_code.core.failures import ExecutionFailure, FailureKind
from free_claude_code.core.trace import trace_event

# Failure kinds that trip the circuit breaker.
_TRIP_KINDS = frozenset(
    {
        FailureKind.RATE_LIMIT,
        FailureKind.OVERLOADED,
        FailureKind.UPSTREAM,
        FailureKind.UNAVAILABLE,
        FailureKind.TIMEOUT,
    }
)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderCircuitBreaker:
    """Track per-provider failure health and short-circuit when a provider is down.

    States:
        CLOSED  — normal; failures are recorded in a sliding window.
        OPEN    — too many recent failures; skip this provider entirely
                  for ``cooldown_seconds``.
        HALF_OPEN — cooldown expired; allow one probe request through.
                  If it succeeds → CLOSED.  If it fails → OPEN again.
    """

    def __init__(
        self,
        provider_id: str,
        *,
        threshold: int = 3,
        cooldown_seconds: float = 120.0,
    ) -> None:
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        self._provider_id = provider_id
        self._threshold = threshold
        # Floor cooldown to 0.1s so a zero-value never collapses the sliding window.
        self._cooldown_seconds = max(cooldown_seconds, 0.1)
        self._failure_times: deque[float] = deque()
        self._state = CircuitState.CLOSED
        self._opened_at: float = 0.0
        self._half_open_probe_used = False

    @property
    def state(self) -> CircuitState:
        """Current circuit state (may transition OPEN → HALF_OPEN on access)."""
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._opened_at >= self._cooldown_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_probe_used = False
        return self._state

    @property
    def is_healthy(self) -> bool:
        """Return whether the provider should receive traffic."""
        s = self.state
        return s != CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful request."""
        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                "CIRCUIT_BREAKER: provider='{}' probe succeeded → CLOSED",
                self._provider_id,
            )
            self._state = CircuitState.CLOSED
            self._failure_times.clear()
            trace_event(
                stage="routing",
                event="free_claude_code.api.circuit_breaker.closed",
                source="api",
                provider_id=self._provider_id,
                reason="probe_succeeded",
            )
            return
        # In CLOSED state, success doesn't clear history — only time expiry does.
        self._prune_old_failures()

    def record_failure(self, error: ExecutionFailure | Exception) -> None:
        """Record a failed request; may trip the breaker."""
        kind = (
            error.kind if isinstance(error, ExecutionFailure) else FailureKind.UPSTREAM
        )
        if kind not in _TRIP_KINDS:
            return  # Not a breaker-relevant failure

        now = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed → re-open immediately.
            self._state = CircuitState.OPEN
            self._opened_at = now
            logger.warning(
                "CIRCUIT_BREAKER: provider='{}' probe failed ({}) → OPEN",
                self._provider_id,
                kind.value,
            )
            trace_event(
                stage="routing",
                event="free_claude_code.api.circuit_breaker.opened",
                source="api",
                provider_id=self._provider_id,
                reason="probe_failed",
                cooldown_seconds=self._cooldown_seconds,
            )
            return

        # CLOSED state — record failure and check threshold.
        self._failure_times.append(now)
        self._prune_old_failures(now)
        if len(self._failure_times) >= self._threshold:
            self._state = CircuitState.OPEN
            self._opened_at = now
            logger.warning(
                "CIRCUIT_BREAKER: provider='{}' tripped ({} recent failures ≥ {}) → OPEN for {}s",
                self._provider_id,
                len(self._failure_times),
                self._threshold,
                self._cooldown_seconds,
            )
            trace_event(
                stage="routing",
                event="free_claude_code.api.circuit_breaker.opened",
                source="api",
                provider_id=self._provider_id,
                reason="threshold_exceeded",
                recent_failures=len(self._failure_times),
                threshold=self._threshold,
                cooldown_seconds=self._cooldown_seconds,
            )

    def _prune_old_failures(self, now: float | None = None) -> None:
        """Drop failure timestamps older than the cooldown window."""
        if now is None:
            now = time.monotonic()
        cutoff = now - self._cooldown_seconds
        while self._failure_times and self._failure_times[0] < cutoff:
            self._failure_times.popleft()


class CircuitBreakerRegistry:
    """Maintain one ``ProviderCircuitBreaker`` per provider id."""

    def __init__(
        self,
        *,
        threshold: int = 3,
        cooldown_seconds: float = 120.0,
    ) -> None:
        self._threshold = threshold
        self._cooldown_seconds = cooldown_seconds
        self._breakers: dict[str, ProviderCircuitBreaker] = {}

    def get(self, provider_id: str) -> ProviderCircuitBreaker:
        """Return the breaker for *provider_id*, creating it on first access."""
        if provider_id not in self._breakers:
            self._breakers[provider_id] = ProviderCircuitBreaker(
                provider_id,
                threshold=self._threshold,
                cooldown_seconds=self._cooldown_seconds,
            )
        return self._breakers[provider_id]

    def status_snapshot(self) -> dict[str, dict[str, str | int]]:
        """Return a snapshot of all breakers for admin/status reporting."""
        return {
            pid: {
                "state": str(b.state),
                "recent_failures": len(b._failure_times),
                "threshold": b._threshold,
            }
            for pid, b in self._breakers.items()
        }
