"""Tests for client credentials auth provider."""

from __future__ import annotations

import httpx
import pytest
import respx

from sp_dl.auth.client_creds import ClientCredentialsAuthProvider
from sp_dl.models import AuthError, AuthMethod


class TestClientCredentialsAuth:
    def test_method_property(self):
        provider = ClientCredentialsAuthProvider(tenant="t", client_id="id", client_secret="secret")
        assert provider.method == AuthMethod.CLIENT_CREDENTIALS

    def test_description(self):
        provider = ClientCredentialsAuthProvider(
            tenant="mytenant", client_id="my-client-id-123", client_secret="secret"
        )
        assert "mytenant" in provider.description
        assert "my-clien" in provider.description

    @respx.mock
    @pytest.mark.asyncio
    async def test_authenticate_success(self):
        respx.post("https://login.microsoftonline.com/mytenant/oauth2/v2.0/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "test-token-abc",
                    "expires_in": 3600,
                },
            )
        )

        provider = ClientCredentialsAuthProvider(
            tenant="mytenant", client_id="cid", client_secret="csecret"
        )
        client = httpx.AsyncClient()
        result = await provider.authenticate(client)

        assert "Bearer test-token-abc" in result.headers.get("Authorization", "")
        await result.aclose()
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_authenticate_failure(self):
        respx.post("https://login.microsoftonline.com/mytenant/oauth2/v2.0/token").mock(
            return_value=httpx.Response(400, text="Bad request")
        )

        provider = ClientCredentialsAuthProvider(
            tenant="mytenant", client_id="cid", client_secret="csecret"
        )
        client = httpx.AsyncClient()
        with pytest.raises(AuthError, match="Client credentials authentication failed"):
            await provider.authenticate(client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_uses_cached_token(self):
        respx.post("https://login.microsoftonline.com/t/oauth2/v2.0/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok1", "expires_in": 3600},
            )
        )

        provider = ClientCredentialsAuthProvider(tenant="t", client_id="c", client_secret="s")
        client = httpx.AsyncClient()

        # First call gets token
        result1 = await provider.authenticate(client)
        assert "Bearer tok1" in result1.headers.get("Authorization", "")

        # Second call should use cached token (no additional HTTP call)
        result2 = await provider.authenticate(client)
        assert "Bearer tok1" in result2.headers.get("Authorization", "")

        await result1.aclose()
        await result2.aclose()
        await client.aclose()

    @pytest.mark.asyncio
    async def test_is_valid_without_token(self):
        provider = ClientCredentialsAuthProvider(tenant="t", client_id="c", client_secret="s")
        client = httpx.AsyncClient()
        assert await provider.is_valid(client) is False
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_valid_with_token(self):
        respx.post(url__regex=r".*token$").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok", "expires_in": 3600},
            )
        )

        provider = ClientCredentialsAuthProvider(tenant="t", client_id="c", client_secret="s")
        client = httpx.AsyncClient()
        await provider.authenticate(client)
        assert await provider.is_valid(client) is True
        await client.aclose()
