"""Tests for SharePoint REST resolver."""

from __future__ import annotations

import httpx
import pytest
import respx

from sp_dl.models import (
    AccessDeniedError,
    FileNotFoundOnServerError,
    ParsedURL,
    URLType,
)
from sp_dl.resolver.sp_rest import SharePointRESTResolver


class TestSharePointRESTResolver:
    def setup_method(self):
        self.resolver = SharePointRESTResolver()

    def test_can_handle_direct_path(self):
        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Docs/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/video.mp4",
        )
        assert self.resolver.can_handle(parsed) is True

    def test_cannot_handle_no_path(self):
        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/:v:/s/Team/abc",
            url_type=URLType.SHARING_LINK,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            sharing_token="abc",
        )
        assert self.resolver.can_handle(parsed) is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_success(self, sp_rest_file_response):
        respx.get(
            url__startswith="https://contoso.sharepoint.com/sites/Team/_api/web/GetFileByServerRelativeUrl"
        ).mock(return_value=httpx.Response(200, json=sp_rest_file_response))

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Docs/training-video.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/Videos/training-video.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert target.metadata.name == "training-video.mp4"
        assert target.metadata.size_bytes == 524288000
        assert target.requires_auth_headers is True
        # Video files use download.aspx with UniqueId instead of $value
        assert "download.aspx" in target.download_url
        assert "UniqueId" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_403_raises_access_denied(self):
        respx.get(url__startswith="https://contoso.sharepoint.com").mock(
            return_value=httpx.Response(403)
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Docs/secret.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/secret.mp4",
        )

        client = httpx.AsyncClient()
        with pytest.raises(AccessDeniedError):
            await self.resolver.resolve(parsed, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_404_raises_resolve_error(self):
        respx.get(url__startswith="https://contoso.sharepoint.com").mock(
            return_value=httpx.Response(404)
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Docs/missing.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/missing.mp4",
        )

        client = httpx.AsyncClient()
        with pytest.raises(FileNotFoundOnServerError, match="not found"):
            await self.resolver.resolve(parsed, client)
        await client.aclose()
