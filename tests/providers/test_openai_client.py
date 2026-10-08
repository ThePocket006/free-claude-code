"""Tests for endpoint-bound OpenAI SDK request clients."""

from unittest.mock import MagicMock

import pytest

from free_claude_code.providers.endpoint_types import HttpEndpoint
from free_claude_code.providers.openai_client import OpenAIRequestClient

pytestmark = pytest.mark.asyncio


def _client() -> MagicMock:
    client = MagicMock()
    client.default_headers = {}
    return client


async def test_for_endpoint_routes_localhost_over_ipv4() -> None:
    client = _client()
    request_client = OpenAIRequestClient(transport=None)
    try:
        request_client.for_endpoint(
            client,
            HttpEndpoint(base_url="http://localhost:9999/v1", headers={}, api_key=None),
        )
    finally:
        await request_client.aclose()
    _, kwargs = client.with_options.call_args
    assert kwargs["base_url"] == "http://127.0.0.1:9999/v1"


async def test_for_endpoint_keeps_remote_base_url() -> None:
    client = _client()
    request_client = OpenAIRequestClient(transport=None)
    try:
        request_client.for_endpoint(
            client,
            HttpEndpoint(
                base_url="https://api.example.com/v1", headers={}, api_key=None
            ),
        )
    finally:
        await request_client.aclose()
    _, kwargs = client.with_options.call_args
    assert kwargs["base_url"] == "https://api.example.com/v1"


async def test_for_endpoint_keeps_config_url_visible_on_endpoint() -> None:
    """The configured URL stays authoritative on the endpoint snapshot."""
    client = _client()
    endpoint = HttpEndpoint(
        base_url="http://localhost:9999/v1", headers={}, api_key=None
    )
    request_client = OpenAIRequestClient(transport=None)
    try:
        request_client.for_endpoint(client, endpoint)
    finally:
        await request_client.aclose()
    assert endpoint.base_url == "http://localhost:9999/v1"