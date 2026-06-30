"""Shutdown drain for PocketOptionAPIClient.

Prevents the SIGSEGV observed 2026-06-30 22:51:36 where a tokio-rt-worker
inside BinaryOptionsToolsV2 called PyGILState_Ensure after Py_Finalize
had begun. close() must await the SDK's shutdown() so the Rust runtime
joins before the interpreter tears down.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from broker.po_api import PocketOptionAPIClient


def test_close_awaits_underlying_shutdown_and_clears_client() -> None:
    client = PocketOptionAPIClient(ssid="dummy", dry_run=True)
    mock_sdk = AsyncMock()
    client._client = mock_sdk

    asyncio.run(client.close())

    mock_sdk.shutdown.assert_awaited_once()
    assert client._client is None


def test_close_is_noop_when_never_connected() -> None:
    client = PocketOptionAPIClient(ssid="dummy", dry_run=True)
    assert client._client is None

    asyncio.run(client.close())

    assert client._client is None


def test_close_swallows_shutdown_errors() -> None:
    client = PocketOptionAPIClient(ssid="dummy", dry_run=True)
    mock_sdk = AsyncMock()
    mock_sdk.shutdown.side_effect = RuntimeError("rust runtime exploded")
    client._client = mock_sdk

    # close() must not raise — the process is already on its way out, and
    # leaking the exception would mask the original reason for exit.
    asyncio.run(client.close())

    mock_sdk.shutdown.assert_awaited_once()
    assert client._client is None


def test_close_is_idempotent() -> None:
    client = PocketOptionAPIClient(ssid="dummy", dry_run=True)
    mock_sdk = AsyncMock()
    client._client = mock_sdk

    asyncio.run(client.close())
    asyncio.run(client.close())  # second call should be a no-op

    mock_sdk.shutdown.assert_awaited_once()


def test_close_is_async() -> None:
    import inspect
    client = PocketOptionAPIClient(ssid="dummy", dry_run=True)
    assert inspect.iscoroutinefunction(client.close)
