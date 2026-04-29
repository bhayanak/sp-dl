"""Tests for sharing link resolver."""

from __future__ import annotations

import httpx
import pytest
import respx

from sp_dl.models import AccessDeniedError, ParsedURL, URLType
from sp_dl.resolver.sharing import SharingLinkResolver, encode_sharing_url


class TestEncodeSharingUrl:
    def test_encode_basic_url(self):
        url = "https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJk"
        encoded = encode_sharing_url(url)
        assert encoded.startswith("u!")
        assert "=" not in encoded  # padding stripped

    def test_encode_is_deterministic(self):
        url = "https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJk"
        assert encode_sharing_url(url) == encode_sharing_url(url)


class TestSharingLinkResolver:
    def setup_method(self):
        self.resolver = SharingLinkResolver()

    def test_can_handle_sharing_link(self):
        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/:v:/s/Team/abc",
            url_type=URLType.SHARING_LINK,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            sharing_token="abc",
        )
        assert self.resolver.can_handle(parsed) is True

    def test_cannot_handle_direct_path(self):
        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/file.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            server_relative_path="/sites/Team/file.mp4",
        )
        assert self.resolver.can_handle(parsed) is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_sharing_link(self, graph_driveitem_response):
        respx.get(url__startswith="https://graph.microsoft.com/v1.0/shares/").mock(
            return_value=httpx.Response(200, json=graph_driveitem_response)
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJk",
            url_type=URLType.SHARING_LINK,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            sharing_token="EaBcDeFgHiJk",
        )

        client = httpx.AsyncClient(headers={"Authorization": "Bearer token"})
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert target.metadata.name == "Q3 All-Hands Recording.mp4"
        assert target.requires_auth_headers is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_403_raises(self):
        respx.get(url__startswith="https://graph.microsoft.com/v1.0/shares/").mock(
            return_value=httpx.Response(403)
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/:v:/s/Team/abc",
            url_type=URLType.SHARING_LINK,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            sharing_token="abc",
        )

        client = httpx.AsyncClient(headers={"Authorization": "Bearer token"})
        with pytest.raises(AccessDeniedError):
            await self.resolver.resolve(parsed, client)
        await client.aclose()
