"""Interactive browser-based OAuth2 authentication."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from sp_dl.auth.base import AuthProvider
from sp_dl.auth.token_cache import TokenCache
from sp_dl.constants import (
    AZURE_AD_AUTHORIZE,
    AZURE_AD_TOKEN,
    DEFAULT_CLIENT_ID,
    DEFAULT_SCOPES,
)
from sp_dl.models import AuthError, AuthMethod

logger = logging.getLogger(__name__)


class InteractiveAuthProvider(AuthProvider):
    """Browser-based OAuth2 authorization code flow."""

    def __init__(
        self,
        tenant: str = "common",
        client_id: str = DEFAULT_CLIENT_ID,
        scopes: list[str] | None = None,
        token_cache: TokenCache | None = None,
        port: int = 0,  # 0 = auto-select
    ):
        self._tenant = tenant
        self._client_id = client_id
        self._scopes = scopes or DEFAULT_SCOPES
        self._token_cache = token_cache or TokenCache()
        self._port = port
        self._access_token: str | None = None

    @property
    def method(self) -> AuthMethod:
        return AuthMethod.INTERACTIVE

    @property
    def description(self) -> str:
        return f"Interactive browser (tenant: {self._tenant})"

    async def authenticate(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        """Authenticate via browser redirect."""
        # Try cached token first
        cached = self._token_cache.load()
        if cached:
            access_token = cached.get("access_token")
            expires_at = cached.get("expires_at", 0)

            if time.time() < expires_at - 300:
                self._access_token = access_token
                return self._build_client(client, access_token)

            refresh_token = cached.get("refresh_token")
            if refresh_token:
                try:
                    token_data = await self._refresh_token(client, refresh_token)
                    self._access_token = token_data["access_token"]
                    return self._build_client(client, self._access_token)
                except AuthError:
                    pass

        # Start interactive flow
        token_data = await self._auth_code_flow(client)
        self._access_token = token_data["access_token"]
        return self._build_client(client, self._access_token)

    async def is_valid(self, client: httpx.AsyncClient) -> bool:
        if not self._access_token:
            return False
        try:
            response = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def _auth_code_flow(self, client: httpx.AsyncClient) -> dict:  # pragma: no cover
        """Run the authorization code flow with a local redirect server."""
        from rich.console import Console

        console = Console()
        state = secrets.token_urlsafe(32)
        auth_code_future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

        # Start local server to capture redirect
        server, port = self._start_redirect_server(state, auth_code_future)
        redirect_uri = f"http://localhost:{port}"

        # Build authorization URL
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(self._scopes),
            "state": state,
            "response_mode": "query",
        }
        auth_url = AZURE_AD_AUTHORIZE.format(tenant=self._tenant) + "?" + urlencode(params)

        console.print()
        console.print("[bold]🔑 Browser Authentication[/bold]")
        console.print()
        console.print("  Opening browser for sign-in...")
        console.print(f"  If browser doesn't open, visit: {auth_url[:80]}...")

        webbrowser.open(auth_url)

        try:
            # Wait for redirect (timeout 120s)
            auth_code = await asyncio.wait_for(auth_code_future, timeout=120.0)
        except asyncio.TimeoutError:
            raise AuthError("Browser authentication timed out after 120 seconds.") from None
        finally:
            server.shutdown()

        # Exchange code for tokens
        token_url = AZURE_AD_TOKEN.format(tenant=self._tenant)
        response = await client.post(
            token_url,
            data={
                "client_id": self._client_id,
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self._scopes),
            },
        )

        if response.status_code != 200:
            raise AuthError(f"Token exchange failed: {response.text}")

        result = response.json()
        result["expires_at"] = time.time() + result.get("expires_in", 3600)
        self._token_cache.save(result)

        console.print("  [green]✓[/green] Authentication successful!")
        return result

    def _start_redirect_server(  # pragma: no cover
        self, expected_state: str, future: asyncio.Future[str]
    ) -> tuple[HTTPServer, int]:
        """Start a local HTTP server to capture the OAuth redirect."""
        loop = asyncio.get_event_loop()

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                params = parse_qs(urlparse(self.path).query)
                state = params.get("state", [""])[0]
                code = params.get("code", [""])[0]
                error = params.get("error", [""])[0]

                if error:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Authentication failed. You can close this window.")
                    loop.call_soon_threadsafe(
                        future.set_exception,
                        AuthError(f"Auth error: {error}"),
                    )
                    return

                if state != expected_state:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Invalid state. Possible CSRF attack.")
                    loop.call_soon_threadsafe(
                        future.set_exception,
                        AuthError("State mismatch in OAuth redirect"),
                    )
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authentication successful!</h2>"
                    b"<p>You can close this window.</p></body></html>"
                )
                loop.call_soon_threadsafe(future.set_result, code)

            def log_message(self, fmt, *args):  # noqa: A002
                pass  # Suppress server logs

        server = HTTPServer(("127.0.0.1", self._port), RedirectHandler)
        port = server.server_address[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, port

    async def _refresh_token(self, client: httpx.AsyncClient, refresh_token: str) -> dict:
        url = AZURE_AD_TOKEN.format(tenant=self._tenant)
        response = await client.post(
            url,
            data={
                "client_id": self._client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(self._scopes),
            },
        )
        if response.status_code != 200:
            raise AuthError(f"Token refresh failed: {response.text}")

        result = response.json()
        result["expires_at"] = time.time() + result.get("expires_in", 3600)
        self._token_cache.save(result)
        return result

    def _build_client(self, base_client: httpx.AsyncClient, token: str) -> httpx.AsyncClient:
        headers = dict(base_client.headers)
        headers["Authorization"] = f"Bearer {token}"
        return httpx.AsyncClient(
            headers=headers,
            timeout=base_client.timeout,
            follow_redirects=True,
        )
