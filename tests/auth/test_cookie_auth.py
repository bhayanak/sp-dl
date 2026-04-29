"""Tests for cookie auth provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from sp_dl.auth.cookie_auth import CookieAuthProvider
from sp_dl.models import AuthError


class TestCookieAuth:
    def test_missing_file_raises(self, tmp_path: Path):
        provider = CookieAuthProvider(cookies_file=tmp_path / "nonexistent.txt")
        import asyncio

        import httpx

        client = httpx.AsyncClient()
        with pytest.raises(AuthError, match="Cookie file not found"):
            asyncio.run(provider.authenticate(client))

    def test_load_valid_cookie_file(self, sample_cookies_file: Path):
        provider = CookieAuthProvider(cookies_file=sample_cookies_file)
        import asyncio

        import httpx

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

        import httpx

        client = httpx.AsyncClient()
        with pytest.raises(AuthError, match="No SharePoint cookies"):
            asyncio.run(provider.authenticate(client))

    def test_unsupported_browser_raises(self):
        provider = CookieAuthProvider(browser="netscape_navigator")

        import asyncio

        import httpx

        client = httpx.AsyncClient()
        with pytest.raises(
            AuthError,
            match="browser-cookie3 package not installed|Unsupported browser",
        ):
            asyncio.run(provider.authenticate(client))
