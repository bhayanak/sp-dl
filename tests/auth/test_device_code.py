"""Tests for device code auth provider."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import respx

from sp_dl.auth.device_code import DeviceCodeAuthProvider
from sp_dl.auth.token_cache import TokenCache
from sp_dl.models import AuthMethod


class TestDeviceCodeAuth:
    def test_method_property(self):
        provider = DeviceCodeAuthProvider()
        assert provider.method == AuthMethod.DEVICE_CODE

    def test_description(self):
        provider = DeviceCodeAuthProvider(tenant="contoso.onmicrosoft.com")
        assert "contoso" in provider.description

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

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_failure_falls_through(self, tmp_path: Path):
        """When refresh fails, should try device code flow."""
        cache = TokenCache(cache_dir=tmp_path)
        cache.save(
            {
                "access_token": "expired",
                "refresh_token": "bad-refresh",
                "expires_at": time.time() - 100,
            }
        )

        # Refresh fails
        respx.post("https://login.microsoftonline.com/t/oauth2/v2.0/token").mock(
            return_value=httpx.Response(400, text="invalid_grant")
        )

        provider = DeviceCodeAuthProvider(tenant="t", token_cache=cache)
        # Mock _device_code_flow to avoid interactive flow
        from unittest.mock import AsyncMock

        provider._device_code_flow = AsyncMock(
            return_value={
                "access_token": "new-device-token",
                "expires_in": 3600,
            }
        )

        client = httpx.AsyncClient()
        result = await provider.authenticate(client)
        assert "Bearer new-device-token" in result.headers.get("Authorization", "")
        provider._device_code_flow.assert_called_once()
        await result.aclose()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_is_valid_without_token(self):
        provider = DeviceCodeAuthProvider()
        client = httpx.AsyncClient()
        assert await provider.is_valid(client) is False
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_valid_with_valid_token(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save(
            {
                "access_token": "good-token",
                "expires_at": time.time() + 3600,
            }
        )

        respx.get("https://graph.microsoft.com/v1.0/me").mock(
            return_value=httpx.Response(200, json={"displayName": "User"})
        )

        provider = DeviceCodeAuthProvider(tenant="t", token_cache=cache)
        client = httpx.AsyncClient()
        await provider.authenticate(client)
        assert await provider.is_valid(client) is True
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_valid_false_on_401(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save(
            {
                "access_token": "bad-token",
                "expires_at": time.time() + 3600,
            }
        )

        respx.get("https://graph.microsoft.com/v1.0/me").mock(return_value=httpx.Response(401))

        provider = DeviceCodeAuthProvider(tenant="t", token_cache=cache)
        client = httpx.AsyncClient()
        await provider.authenticate(client)
        assert await provider.is_valid(client) is False
        await client.aclose()

    def test_custom_scopes(self):
        provider = DeviceCodeAuthProvider(
            scopes=["https://contoso.sharepoint.com/.default", "offline_access"]
        )
        assert "sharepoint.com" in provider._scopes[0]

    def test_custom_client_id(self):
        provider = DeviceCodeAuthProvider(client_id="custom-id")
        assert provider._client_id == "custom-id"
