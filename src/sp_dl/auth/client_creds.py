"""Client Credentials (service account) authentication."""

from __future__ import annotations

import logging
import time

import httpx

from sp_dl.auth.base import AuthProvider
from sp_dl.constants import AZURE_AD_TOKEN
from sp_dl.models import AuthError, AuthMethod

logger = logging.getLogger(__name__)


class ClientCredentialsAuthProvider(AuthProvider):
    """OAuth2 Client Credentials flow for service accounts."""

    def __init__(
        self,
        tenant: str,
        client_id: str,
        client_secret: str,
        scope: str = "https://graph.microsoft.com/.default",
    ):
        self._tenant = tenant
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._access_token: str | None = None
        self._expires_at: float = 0

    @property
    def method(self) -> AuthMethod:
        return AuthMethod.CLIENT_CREDENTIALS

    @property
    def description(self) -> str:
        return f"Client credentials (tenant: {self._tenant}, app: {self._client_id[:8]}...)"

    async def authenticate(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        """Obtain an access token using client credentials."""
        if self._access_token and time.time() < self._expires_at - 300:
            return self._build_client(client, self._access_token)

        url = AZURE_AD_TOKEN.format(tenant=self._tenant)
        response = await client.post(
            url,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": self._scope,
                "grant_type": "client_credentials",
            },
        )

        if response.status_code != 200:
            raise AuthError(
                f"Client credentials authentication failed: {response.text}\n"
                "Ensure the app registration has the correct permissions "
                "and admin consent has been granted."
            )

        result = response.json()
        self._access_token = result["access_token"]
        self._expires_at = time.time() + result.get("expires_in", 3600)

        return self._build_client(client, self._access_token)

    async def is_valid(self, client: httpx.AsyncClient) -> bool:
        if not self._access_token:
            return False
        return time.time() < self._expires_at - 300

    def _build_client(self, base_client: httpx.AsyncClient, token: str) -> httpx.AsyncClient:
        headers = dict(base_client.headers)
        headers["Authorization"] = f"Bearer {token}"
        return httpx.AsyncClient(
            headers=headers,
            timeout=base_client.timeout,
            follow_redirects=True,
        )
