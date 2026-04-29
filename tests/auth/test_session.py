"""Tests for auth session factory and builder."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from sp_dl.auth.client_creds import ClientCredentialsAuthProvider
from sp_dl.auth.cookie_auth import CookieAuthProvider
from sp_dl.auth.device_code import DeviceCodeAuthProvider
from sp_dl.auth.interactive import InteractiveAuthProvider
from sp_dl.auth.session import build_session, create_auth_provider
from sp_dl.models import AuthError, AuthMethod


class TestCreateAuthProvider:
    def test_auto_detect_cookies_file(self, tmp_path: Path):
        provider = create_auth_provider(cookies_file=tmp_path / "c.txt")
        assert isinstance(provider, CookieAuthProvider)

    def test_auto_detect_cookies_browser(self):
        provider = create_auth_provider(cookies_from_browser="chrome")
        assert isinstance(provider, CookieAuthProvider)

    def test_auto_detect_client_credentials(self):
        provider = create_auth_provider(client_id="id", client_secret="secret")
        assert isinstance(provider, ClientCredentialsAuthProvider)

    def test_auto_detect_default_device_code(self):
        provider = create_auth_provider()
        assert isinstance(provider, DeviceCodeAuthProvider)

    def test_explicit_device_code(self):
        provider = create_auth_provider(
            method=AuthMethod.DEVICE_CODE, tenant="contoso.onmicrosoft.com"
        )
        assert isinstance(provider, DeviceCodeAuthProvider)

    def test_explicit_interactive(self):
        provider = create_auth_provider(method=AuthMethod.INTERACTIVE)
        assert isinstance(provider, InteractiveAuthProvider)

    def test_explicit_cookies(self, tmp_path: Path):
        provider = create_auth_provider(
            method=AuthMethod.COOKIES,
            cookies_file=tmp_path / "c.txt",
        )
        assert isinstance(provider, CookieAuthProvider)

    def test_explicit_client_credentials_missing_secret(self):
        with pytest.raises(AuthError, match="Client credentials require"):
            create_auth_provider(
                method=AuthMethod.CLIENT_CREDENTIALS,
                client_id="id",
            )

    def test_explicit_client_credentials_missing_id(self):
        with pytest.raises(AuthError, match="Client credentials require"):
            create_auth_provider(
                method=AuthMethod.CLIENT_CREDENTIALS,
                client_secret="secret",
            )

    def test_explicit_client_credentials(self):
        provider = create_auth_provider(
            method=AuthMethod.CLIENT_CREDENTIALS,
            client_id="id",
            client_secret="secret",
            tenant="mytenant",
        )
        assert isinstance(provider, ClientCredentialsAuthProvider)

    def test_device_code_with_tenant_generates_sp_scopes(self):
        provider = create_auth_provider(
            method=AuthMethod.DEVICE_CODE,
            tenant="contoso.onmicrosoft.com",
        )
        assert isinstance(provider, DeviceCodeAuthProvider)
        # Provider should have SharePoint-specific scopes
        assert any("sharepoint.com" in s for s in provider._scopes)

    def test_device_code_common_tenant_no_sp_scopes(self):
        provider = create_auth_provider(
            method=AuthMethod.DEVICE_CODE,
            tenant="common",
        )
        assert isinstance(provider, DeviceCodeAuthProvider)

    def test_custom_client_id_for_device_code(self):
        provider = create_auth_provider(
            method=AuthMethod.DEVICE_CODE,
            client_id="custom-id",
        )
        assert isinstance(provider, DeviceCodeAuthProvider)
        assert provider._client_id == "custom-id"


class TestBuildSession:
    @respx.mock
    @pytest.mark.asyncio
    async def test_build_session_returns_client(self, sample_cookies_file: Path):
        provider = CookieAuthProvider(cookies_file=sample_cookies_file)
        client = await build_session(provider)
        assert isinstance(client, httpx.AsyncClient)
        assert "sp-dl" in client.headers.get("User-Agent", "")
        await client.aclose()
