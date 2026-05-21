"""Cookie-based authentication for SharePoint."""

from __future__ import annotations

import http.cookiejar
import logging
from pathlib import Path

import httpx

from sp_dl.auth.base import AuthProvider
from sp_dl.constants import REQUIRED_COOKIES
from sp_dl.models import AuthError, AuthMethod

logger = logging.getLogger(__name__)


class CookieAuthProvider(AuthProvider):
    """Authenticate using exported browser cookies (Netscape format)."""

    def __init__(self, cookies_file: Path | None = None):
        self._cookies_file = cookies_file
        self._cookie_jar: http.cookiejar.MozillaCookieJar | None = None

    @property
    def method(self) -> AuthMethod:
        return AuthMethod.COOKIES

    @property
    def description(self) -> str:
        if self._cookies_file:
            return f"Cookie-based (file: {self._cookies_file.name})"
        return "Cookie-based"

    async def authenticate(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        """Load cookies and apply to the client."""
        if self._cookies_file:
            cookies = self._load_cookie_file(self._cookies_file)
        else:
            raise AuthError("No cookie file specified")

        # Validate that required cookies are present
        cookie_names = {c.name for c in cookies}
        missing = set(REQUIRED_COOKIES) - cookie_names
        if missing:
            logger.warning(
                f"Missing recommended cookies: {', '.join(missing)}. Authentication may fail."
            )

        # Build httpx cookies from jar
        httpx_cookies = httpx.Cookies()
        for cookie in cookies:
            httpx_cookies.set(
                cookie.name,
                cookie.value,
                domain=cookie.domain,
                path=cookie.path,
            )

        # Create new client with cookies
        return httpx.AsyncClient(
            cookies=httpx_cookies,
            headers=client.headers,
            timeout=client.timeout,
            follow_redirects=True,
        )

    async def is_valid(self, client: httpx.AsyncClient) -> bool:
        """Validate cookies by checking if FedAuth is present and not obviously expired."""
        if not client.cookies:
            return False

        cookie_names = set()
        for cookie in client.cookies.jar:
            cookie_names.add(cookie.name)

        # At minimum, FedAuth should be present
        return "FedAuth" in cookie_names or "SPOIDCRL" in cookie_names

    def _load_cookie_file(self, path: Path) -> http.cookiejar.MozillaCookieJar:
        """Load a Netscape-format cookie file."""
        if not path.exists():
            raise AuthError(f"Cookie file not found: {path}")

        jar = http.cookiejar.MozillaCookieJar(str(path))
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as e:
            raise AuthError(
                f"Failed to parse cookie file: {path}\n"
                f"Error: {e}\n"
                "Ensure the file is in Netscape/Mozilla cookie format.\n"
                "Each line should be: domain\\tflag\\tpath\\tsecure\\texpiry\\tname\\tvalue"
            ) from e

        self._cookie_jar = jar
        sp_cookies = [c for c in jar if ".sharepoint.com" in (c.domain or "")]

        if not sp_cookies:
            raise AuthError(
                f"No SharePoint cookies found in {path}.\n"
                "Ensure you exported cookies from a SharePoint session."
            )

        logger.info(f"Loaded {len(sp_cookies)} SharePoint cookies from {path}")
        return jar
