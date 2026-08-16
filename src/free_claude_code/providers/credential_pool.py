"""Rotating credential pool for multiple API keys of one provider."""

import asyncio
import time
from collections.abc import Sequence

import openai

from free_claude_code.core.failures import ExecutionFailure, FailureKind
from free_claude_code.providers.failure_policy import (
    retryable_transient_status,
)

# Cooldown applied to a key after a transient quota/availability failure.
_COOLDOWN_SECONDS = 60.0


class CredentialPool:
    """Serve multiple API keys for one provider, rotating away from failures.

    Implements the ``OpenAIAsyncCredentialProvider`` contract: the OpenAI SDK
    awaits ``__call__`` lazily before each request, so a fresh key is picked
    after ``rotate_on_failure`` marks the previous one unusable.

    - 401 / 403 (or canonical AUTHENTICATION / PERMISSION failures) drop the
      key permanently: a bad key will not keep failing the whole pool.
    - Transient failures (429 rate limit, 5xx overload, timeouts) put the key
      into a short cooldown so healthy keys are preferred immediately, while
      the cooled key recovers after ``_COOLDOWN_SECONDS``.
    """

    def __init__(
        self,
        keys: Sequence[str],
        *,
        cooldown_seconds: float = _COOLDOWN_SECONDS,
    ) -> None:
        self._keys: list[str] = [key for key in keys if key and key.strip()]
        if not self._keys:
            raise ValueError("CredentialPool requires at least one non-empty key")
        self._cooldown_seconds = cooldown_seconds
        self._dead: set[str] = set()
        self._cool_until: dict[str, float] = {}
        self._cursor = 0
        self._last_key: str | None = None
        self._lock = asyncio.Lock()

    @property
    def key_count(self) -> int:
        """Return the number of keys this pool manages."""
        return len(self._keys)

    async def __call__(self) -> str:
        """Return the next usable key (round-robin, skipping dead/cooling)."""
        async with self._lock:
            self._last_key = self._next_usable_key()
            return self._last_key

    def _next_usable_key(self) -> str:
        now = time.monotonic()
        for _ in range(len(self._keys)):
            index = self._cursor % len(self._keys)
            self._cursor += 1
            key = self._keys[index]
            if key in self._dead:
                continue
            cool_until = self._cool_until.get(key, 0.0)
            if cool_until > now:
                continue
            return key
        return self._last_key or self._keys[self._cursor % len(self._keys)]

    async def rotate_on_failure(self, error: BaseException) -> bool:
        """Mark the last key failed and return whether a different key remains.

        A returned ``True`` means the next ``__call__`` will hand out a
        different key; ``False`` means no healthier key is available right now.
        """
        async with self._lock:
            if self._last_key is None:
                return False
            key = self._last_key
            if self._is_permanent_auth_failure(error):
                self._dead.add(key)
                self._cool_until.pop(key, None)
            elif retryable_transient_status(error) is not None:
                self._cool_until[key] = time.monotonic() + self._cooldown_seconds
            else:
                return False
            return self._has_other_usable_key(key)

    @staticmethod
    def _is_permanent_auth_failure(error: BaseException) -> bool:
        """Return whether the error means this key is invalid (401/403)."""
        if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
            return True
        if isinstance(error, ExecutionFailure):
            return error.kind in {
                FailureKind.AUTHENTICATION,
                FailureKind.PERMISSION,
            }
        status = retryable_transient_status(error)
        return status == 401 or status == 403

    def _has_other_usable_key(self, excluded: str) -> bool:
        now = time.monotonic()
        for key in self._keys:
            if key == excluded or key in self._dead:
                continue
            if self._cool_until.get(key, 0.0) > now:
                continue
            return True
        return False
