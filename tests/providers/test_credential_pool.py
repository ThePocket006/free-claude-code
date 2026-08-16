"""CredentialPool rotation contracts."""

import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from free_claude_code.core.failures import ExecutionFailure, FailureKind
from free_claude_code.providers.credential_pool import CredentialPool


def _api_error(cls: type, status: int) -> Exception:
    response = httpx.Response(status, request=httpx.Request("POST", "http://x"))
    return cls(f"status {status}", response=response, body={})


@pytest.mark.asyncio
async def test_pool_hands_out_keys_round_robin() -> None:
    pool = CredentialPool(["sk-a", "sk-b", "sk-c"])

    keys = [await pool(), await pool(), await pool()]

    assert keys == ["sk-a", "sk-b", "sk-c"]


@pytest.mark.asyncio
async def test_pool_rotates_after_rate_limit() -> None:
    pool = CredentialPool(["sk-a", "sk-b", "sk-c"])
    await pool()

    rotated = await pool.rotate_on_failure(_api_error(RateLimitError, 429))
    next_key = await pool()

    assert rotated is True
    assert next_key == "sk-b"


@pytest.mark.asyncio
async def test_pool_drops_key_permanently_on_authentication_error() -> None:
    pool = CredentialPool(["sk-a", "sk-b"])
    await pool()

    await pool.rotate_on_failure(_api_error(AuthenticationError, 401))
    await pool.rotate_on_failure(_api_error(AuthenticationError, 401))

    # Both keys now dead: every call must still return the fallback, but no
    # healthy key remains.
    assert await pool() in ("sk-a", "sk-b")


@pytest.mark.asyncio
async def test_pool_rotates_on_execution_failure_rate_limit() -> None:
    pool = CredentialPool(["sk-a", "sk-b"])
    await pool()
    failure = ExecutionFailure(
        kind=FailureKind.RATE_LIMIT,
        status_code=429,
        message="rate limited",
        retryable=True,
    )

    rotated = await pool.rotate_on_failure(failure)

    assert rotated is True
    assert await pool() == "sk-b"


@pytest.mark.asyncio
async def test_pool_returns_false_when_no_other_key_usable() -> None:
    pool = CredentialPool(["sk-a"])
    await pool()

    rotated = await pool.rotate_on_failure(_api_error(RateLimitError, 429))

    assert rotated is False


@pytest.mark.asyncio
async def test_pool_cooldown_recovers_key() -> None:
    pool = CredentialPool(["sk-a", "sk-b"], cooldown_seconds=0.0)
    await pool()

    await pool.rotate_on_failure(_api_error(RateLimitError, 429))

    # Cooldown of zero means the key is immediately usable again.
    assert await pool() in ("sk-a", "sk-b")


def test_pool_rejects_empty_keys() -> None:
    with pytest.raises(ValueError, match="requires at least one"):
        CredentialPool([" ", ""])


@pytest.mark.asyncio
async def test_pool_does_not_rotate_on_unclassified_error() -> None:
    pool = CredentialPool(["sk-a", "sk-b"])
    await pool()

    rotated = await pool.rotate_on_failure(ValueError("boom"))

    assert rotated is False
    assert await pool() == "sk-b"
