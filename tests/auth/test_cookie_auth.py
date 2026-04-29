"""Tests for cookie auth provider."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from sp_dl.auth.cookie_auth import CookieAuthProvider
from sp_dl.models import AuthError, AuthMethod


class TestCookieAuth:
    def test_method_property(self):
        provider = CookieAuthProvider(cookies_file=Path("x"))
        assert provider.method == AuthMethod.COOKIES

    def test_description_file(self):
        provider = CookieAuthProvider(cookies_file=Path("/tmp/cookies.txt"))
        assert "cookies.txt" in provider.description

    def test_description_browser(self):
        provider = CookieAuthProvider(browser="chrome")
        assert "chrome" in provider.description

    def test_description_neither(self):
        provider = CookieAuthProvider()
        assert "Cookie-based" in provider.description

    def test_missing_file_raises(self, tmp_path: Path):
        provider = CookieAuthProvider(cookies_file=tmp_path / "nonexistent.txt")
        import asyncio

        client = httpx.AsyncClient()
        with pytest.raises(AuthError, match="Cookie file not found"):
            asyncio.run(provider.authenticate(client))

    def test_load_valid_cookie_file(self, sample_cookies_file: Path):
        provider = CookieAuthProvider(cookies_file=sample_cookies_file)
        import asyncio

        client = httpx.AsyncClient()
        result = asyncio.run(provider.authenticate(client))
        # Should return a client with cookies set
        assert result is not None
        asyncio.run(result.aclose())

    def test_empty_cookie_file_raises(self, tmp_path: Path):
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("# Netscape HTTP Cookie File\n")
        provider = CookieAuthProvider(cookies_file=empty_file)

        import asyncio

        client = httpx.AsyncClient()
        with pytest.raises(AuthError, match="No SharePoint cookies"):
            asyncio.run(provider.authenticate(client))

    def test_unsupported_browser_raises(self):
        provider = CookieAuthProvider(browser="netscape_navigator")

        import asyncio

        client = httpx.AsyncClient()
        with pytest.raises(
            AuthError,
            match="browser-cookie3 package not installed|Unsupported browser",
        ):
            asyncio.run(provider.authenticate(client))

    def test_no_source_raises(self):
        provider = CookieAuthProvider()

        import asyncio

        client = httpx.AsyncClient()
        with pytest.raises(AuthError, match="No cookie file or browser"):
            asyncio.run(provider.authenticate(client))

    @pytest.mark.asyncio
    async def test_is_valid_with_fedauth(self, sample_cookies_file: Path):
        provider = CookieAuthProvider(cookies_file=sample_cookies_file)
        client = httpx.AsyncClient()
        result = await provider.authenticate(client)
        assert await provider.is_valid(result) is True
        await result.aclose()

    @pytest.mark.asyncio
    async def test_is_valid_no_cookies(self):
        provider = CookieAuthProvider(cookies_file=Path("x"))
        client = httpx.AsyncClient()
        assert await provider.is_valid(client) is False

    def test_bad_cookie_file_format(self, tmp_path: Path):
        bad_file = tmp_path / "bad.txt"
        bad_file.write_bytes(b"\x00\x01\x02 binary garbage")
        provider = CookieAuthProvider(cookies_file=bad_file)

        import asyncio

        client = httpx.AsyncClient()
        with pytest.raises(AuthError, match="Failed to parse cookie file|No SharePoint cookies"):
            asyncio.run(provider.authenticate(client))
