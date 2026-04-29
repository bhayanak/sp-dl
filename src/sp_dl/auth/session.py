"""Build authenticated httpx.AsyncClient sessions."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from sp_dl.auth.base import AuthProvider
from sp_dl.auth.client_creds import ClientCredentialsAuthProvider
from sp_dl.auth.cookie_auth import CookieAuthProvider
from sp_dl.auth.device_code import DeviceCodeAuthProvider
from sp_dl.auth.interactive import InteractiveAuthProvider
from sp_dl.constants import DEFAULT_TIMEOUT
from sp_dl.models import AuthMethod

logger = logging.getLogger(__name__)


def create_auth_provider(
    method: AuthMethod | None = None,
    cookies_file: Path | None = None,
    cookies_from_browser: str | None = None,
    tenant: str = "common",
    client_id: str | None = None,
    client_secret: str | None = None,
) -> AuthProvider:
    """Create the appropriate auth provider based on parameters."""
    from sp_dl.constants import DEFAULT_CLIENT_ID

    # Auto-detect method if not specified
    if method is None:
        if cookies_file or cookies_from_browser:
            method = AuthMethod.COOKIES
        elif client_id and client_secret:
            method = AuthMethod.CLIENT_CREDENTIALS
        else:
            # Default to device code flow
            method = AuthMethod.DEVICE_CODE

    if method == AuthMethod.COOKIES:
        return CookieAuthProvider(
            cookies_file=cookies_file,
            browser=cookies_from_browser,
        )
    elif method == AuthMethod.DEVICE_CODE:
        # Use SharePoint-specific scopes when tenant is known
        scopes = None
        if tenant and tenant != "common":
            # Derive SharePoint domain from tenant
            # e.g. "contoso.onmicrosoft.com" → "contoso.sharepoint.com"
            tenant_base = tenant.replace(".onmicrosoft.com", "")
            sp_domain = f"{tenant_base}.sharepoint.com"
            scopes = [f"https://{sp_domain}/.default", "offline_access"]
        return DeviceCodeAuthProvider(
            tenant=tenant,
            client_id=client_id or DEFAULT_CLIENT_ID,
            scopes=scopes,
        )
    elif method == AuthMethod.INTERACTIVE:
        return InteractiveAuthProvider(
            tenant=tenant,
            client_id=client_id or DEFAULT_CLIENT_ID,
        )
    elif method == AuthMethod.CLIENT_CREDENTIALS:
        if not client_id or not client_secret:
            from sp_dl.models import AuthError

            raise AuthError("Client credentials require both --client-id and --client-secret")
        return ClientCredentialsAuthProvider(
            tenant=tenant,
            client_id=client_id,
            client_secret=client_secret,
        )
    else:
        from sp_dl.models import AuthError

        raise AuthError(f"Unknown auth method: {method}")


async def build_session(auth_provider: AuthProvider) -> httpx.AsyncClient:
    """Build an authenticated httpx.AsyncClient using the given auth provider."""
    base_client = httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT, read=300.0),
        follow_redirects=True,
        headers={
            "User-Agent": "sp-dl/0.1.0",
            "Accept": "application/json;odata=verbose",
            "X-FORMS_BASED_AUTH_ACCEPTED": "f",
        },
    )

    return await auth_provider.authenticate(base_client)
