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

    def __init__(self, cookies_file: Path | None = None, browser: str | None = None):
        self._cookies_file = cookies_file
        self._browser = browser
        self._cookie_jar: http.cookiejar.MozillaCookieJar | None = None

    @property
    def method(self) -> AuthMethod:
        return AuthMethod.COOKIES

    @property
    def description(self) -> str:
        if self._cookies_file:
            return f"Cookie-based (file: {self._cookies_file.name})"
        if self._browser:
            return f"Cookie-based (from {self._browser})"
        return "Cookie-based"

    async def authenticate(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        """Load cookies and apply to the client."""
        if self._cookies_file:
            cookies = self._load_cookie_file(self._cookies_file)
        elif self._browser:
            cookies = self._extract_from_browser(self._browser)
        else:
            raise AuthError("No cookie file or browser specified")

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

    def _extract_from_browser(self, browser: str) -> http.cookiejar.CookieJar:
        """Extract cookies from installed browser."""
        try:
            import browser_cookie3
        except ImportError:
            raise AuthError(
                "browser-cookie3 package not installed.\n"
                "Install with: pip install sp-dl[browser-cookies]\n"
                "Or export cookies manually to a file."
            ) from None

        browser_lower = browser.lower()
        extractors = {
            "chrome": browser_cookie3.chrome,
            "firefox": browser_cookie3.firefox,
            "edge": browser_cookie3.edge,
            "opera": browser_cookie3.opera,
            "brave": browser_cookie3.brave,
            "chromium": browser_cookie3.chromium,
        }

        extractor = extractors.get(browser_lower)
        if not extractor:
            raise AuthError(
                f"Unsupported browser: {browser}\nSupported: {', '.join(extractors.keys())}"
            )

        try:
            jar = extractor(domain_name=".sharepoint.com")
        except Exception as e:
            raise AuthError(
                f"Failed to extract cookies from {browser}: {e}\n"
                "Make sure the browser is closed or try exporting cookies manually."
            ) from e

        sp_cookies = [c for c in jar if ".sharepoint.com" in (c.domain or "")]
        if not sp_cookies:
            raise AuthError(
                f"No SharePoint cookies found in {browser}.\n"
                "Make sure you're logged into SharePoint in that browser."
            )

        logger.info(f"Extracted {len(sp_cookies)} SharePoint cookies from {browser}")
        return jar
