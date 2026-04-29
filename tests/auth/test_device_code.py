"""Tests for device code auth provider."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import respx

from sp_dl.auth.device_code import DeviceCodeAuthProvider
from sp_dl.auth.token_cache import TokenCache


class TestDeviceCodeAuth:
    @respx.mock
    @pytest.mark.asyncio
    async def test_uses_cached_valid_token(self, tmp_path: Path):
        """Should use cached token if still valid."""
        cache = TokenCache(cache_dir=tmp_path)
        token_data = {
            "access_token": "cached-token-123",
            "refresh_token": "refresh-123",
            "expires_at": time.time() + 3600,
        }
        cache.save(token_data)

        provider = DeviceCodeAuthProvider(
            tenant="contoso.onmicrosoft.com",
            token_cache=cache,
        )

        client = httpx.AsyncClient()
        result = await provider.authenticate(client)

        assert "Bearer cached-token-123" in result.headers.get("Authorization", "")
        await result.aclose()
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, tmp_path: Path):
        """Should refresh token when expired."""
        cache = TokenCache(cache_dir=tmp_path)
        token_data = {
            "access_token": "expired-token",
            "refresh_token": "valid-refresh",
            "expires_at": time.time() - 100,  # expired
        }
        cache.save(token_data)

        # Mock token refresh endpoint
        respx.post(
            "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new-token-456",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            )
        )

        provider = DeviceCodeAuthProvider(
            tenant="contoso.onmicrosoft.com",
            token_cache=cache,
        )

        client = httpx.AsyncClient()
        result = await provider.authenticate(client)

        assert "Bearer new-token-456" in result.headers.get("Authorization", "")
        await result.aclose()
        await client.aclose()
