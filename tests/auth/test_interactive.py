"""Tests for interactive auth provider."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import respx

from sp_dl.auth.interactive import InteractiveAuthProvider
from sp_dl.auth.token_cache import TokenCache
from sp_dl.models import AuthMethod


class TestInteractiveAuth:
    def test_method_property(self):
        provider = InteractiveAuthProvider()
        assert provider.method == AuthMethod.INTERACTIVE

    def test_description(self):
        provider = InteractiveAuthProvider(tenant="contoso.onmicrosoft.com")
        assert "contoso" in provider.description
        assert "Interactive" in provider.description

    @respx.mock
    @pytest.mark.asyncio
    async def test_uses_cached_valid_token(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save(
            {
                "access_token": "cached-token",
                "refresh_token": "refresh-tok",
                "expires_at": time.time() + 3600,
            }
        )

        provider = InteractiveAuthProvider(
            tenant="contoso.onmicrosoft.com",
            token_cache=cache,
        )

        client = httpx.AsyncClient()
        result = await provider.authenticate(client)
        assert "Bearer cached-token" in result.headers.get("Authorization", "")
        await result.aclose()
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save(
            {
                "access_token": "expired",
                "refresh_token": "valid-refresh",
                "expires_at": time.time() - 100,
            }
        )

        respx.post(
            "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "new-token",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            )
        )

        provider = InteractiveAuthProvider(
            tenant="contoso.onmicrosoft.com",
            token_cache=cache,
        )

        client = httpx.AsyncClient()
        result = await provider.authenticate(client)
        assert "Bearer new-token" in result.headers.get("Authorization", "")
        await result.aclose()
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_valid_false_without_token(self):
        provider = InteractiveAuthProvider()
        client = httpx.AsyncClient()
        assert await provider.is_valid(client) is False
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_valid_true_with_valid_token(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save(
            {
                "access_token": "valid-token",
                "expires_at": time.time() + 3600,
            }
        )

        respx.get("https://graph.microsoft.com/v1.0/me").mock(
            return_value=httpx.Response(200, json={"displayName": "User"})
        )

        provider = InteractiveAuthProvider(
            tenant="t",
            token_cache=cache,
        )

        client = httpx.AsyncClient()
        await provider.authenticate(client)
        assert await provider.is_valid(client) is True
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_valid_false_on_http_error(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save(
            {
                "access_token": "bad-token",
                "expires_at": time.time() + 3600,
            }
        )

        respx.get("https://graph.microsoft.com/v1.0/me").mock(return_value=httpx.Response(401))

        provider = InteractiveAuthProvider(
            tenant="t",
            token_cache=cache,
        )

        client = httpx.AsyncClient()
        await provider.authenticate(client)
        assert await provider.is_valid(client) is False
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_refresh_failure_falls_through(self, tmp_path: Path):
        """When refresh fails, should fall through to interactive flow."""
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

        provider = InteractiveAuthProvider(tenant="t", token_cache=cache)
        # Mock _auth_code_flow to avoid the 120s browser timeout
        from unittest.mock import AsyncMock

        provider._auth_code_flow = AsyncMock(
            return_value={
                "access_token": "new-from-flow",
                "expires_in": 3600,
            }
        )

        client = httpx.AsyncClient()
        result = await provider.authenticate(client)
        assert "Bearer new-from-flow" in result.headers.get("Authorization", "")
        provider._auth_code_flow.assert_called_once()
        await result.aclose()
        await client.aclose()

    def test_custom_port(self):
        provider = InteractiveAuthProvider(port=8080)
        assert provider._port == 8080

    def test_custom_scopes(self):
        provider = InteractiveAuthProvider(scopes=["https://contoso.sharepoint.com/.default"])
        assert "sharepoint.com" in provider._scopes[0]
