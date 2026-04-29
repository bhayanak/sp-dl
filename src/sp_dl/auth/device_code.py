"""OAuth2 Device Code Flow authentication."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from sp_dl.auth.base import AuthProvider
from sp_dl.auth.token_cache import TokenCache
from sp_dl.constants import (
    AZURE_AD_DEVICE_CODE,
    AZURE_AD_TOKEN,
    DEFAULT_CLIENT_ID,
    DEFAULT_SCOPES,
)
from sp_dl.models import AuthError, AuthMethod

logger = logging.getLogger(__name__)


class DeviceCodeAuthProvider(AuthProvider):
    """OAuth2 Device Code Flow for headless/CLI scenarios."""

    def __init__(
        self,
        tenant: str = "common",
        client_id: str = DEFAULT_CLIENT_ID,
        scopes: list[str] | None = None,
        token_cache: TokenCache | None = None,
    ):
        self._tenant = tenant
        self._client_id = client_id
        self._scopes = scopes or DEFAULT_SCOPES
        self._token_cache = token_cache or TokenCache()
        self._access_token: str | None = None

    @property
    def method(self) -> AuthMethod:
        return AuthMethod.DEVICE_CODE

    @property
    def description(self) -> str:
        return f"Device code (tenant: {self._tenant})"

    async def authenticate(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        """Authenticate using device code flow or cached token."""
        # Try cached token first
        cached = self._token_cache.load()
        if cached:
            access_token = cached.get("access_token")
            expires_at = cached.get("expires_at", 0)

            if time.time() < expires_at - 300:  # 5 min buffer
                self._access_token = access_token
                return self._build_client(client, access_token)

            # Try refresh
            refresh_token = cached.get("refresh_token")
            if refresh_token:
                try:
                    token_data = await self._refresh_token(client, refresh_token)
                    self._access_token = token_data["access_token"]
                    return self._build_client(client, self._access_token)
                except AuthError:
                    logger.warning("Token refresh failed, starting new device code flow")

        # No valid cached token — start device code flow
        token_data = await self._device_code_flow(client)
        self._access_token = token_data["access_token"]
        return self._build_client(client, self._access_token)

    async def is_valid(self, client: httpx.AsyncClient) -> bool:
        """Check if access token is valid."""
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

    async def _device_code_flow(self, client: httpx.AsyncClient) -> dict:  # pragma: no cover
        """Execute the device code flow interactively."""
        from rich.console import Console

        console = Console()

        # Step 1: Request device code
        url = AZURE_AD_DEVICE_CODE.format(tenant=self._tenant)
        response = await client.post(
            url,
            data={
                "client_id": self._client_id,
                "scope": " ".join(self._scopes),
            },
        )

        if response.status_code != 200:
            raise AuthError(f"Failed to get device code: {response.text}")

        data = response.json()
        device_code = data["device_code"]
        user_code = data["user_code"]
        verification_uri = data["verification_uri"]
        interval = data.get("interval", 5)
        expires_in = data.get("expires_in", 900)

        # Display instructions to user
        console.print()
        console.print("[bold]🔑 Device Code Authentication[/bold]")
        console.print()
        console.print(f"  1. Open: [link={verification_uri}]{verification_uri}[/link]")
        console.print(f"  2. Enter code: [bold cyan]{user_code}[/bold cyan]")
        console.print()
        console.print("  Waiting for you to complete sign-in...", style="dim")

        # Step 2: Poll for token
        token_url = AZURE_AD_TOKEN.format(tenant=self._tenant)
        deadline = time.time() + expires_in

        while time.time() < deadline:
            await asyncio.sleep(interval)

            response = await client.post(
                token_url,
                data={
                    "client_id": self._client_id,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                },
            )

            result = response.json()

            if "access_token" in result:
                # Success
                result["expires_at"] = time.time() + result.get("expires_in", 3600)
                self._token_cache.save(result)
                console.print("  [green]✓[/green] Authentication successful!")
                return result

            error = result.get("error", "")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 5
                continue
            elif error == "authorization_declined":
                raise AuthError("Authentication was declined by user.")
            elif error == "expired_token":
                raise AuthError("Device code expired. Please try again.")
            else:
                raise AuthError(f"Authentication failed: {result.get('error_description', error)}")

        raise AuthError("Device code flow timed out. Please try again.")

    async def _refresh_token(self, client: httpx.AsyncClient, refresh_token: str) -> dict:
        """Refresh an expired access token."""
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
        """Build a new client with the Authorization header."""
        headers = dict(base_client.headers)
        headers["Authorization"] = f"Bearer {token}"

        return httpx.AsyncClient(
            headers=headers,
            timeout=base_client.timeout,
            follow_redirects=True,
        )
