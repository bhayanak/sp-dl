"""Tests for SharePoint REST resolver."""

from __future__ import annotations

import httpx
import pytest
import respx

from sp_dl.models import (
    AccessDeniedError,
    FileNotFoundOnServerError,
    ParsedURL,
    ResolveError,
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

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_401_raises_access_denied(self):
        respx.get(url__startswith="https://contoso.sharepoint.com").mock(
            return_value=httpx.Response(401)
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Docs/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/v.mp4",
        )

        client = httpx.AsyncClient()
        with pytest.raises(AccessDeniedError):
            await self.resolver.resolve(parsed, client)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_resolve_no_path_raises(self):
        parsed = ParsedURL(
            original_url="https://x.sharepoint.com/...",
            url_type=URLType.DIRECT_PATH,
            tenant="x",
            tenant_domain="x.sharepoint.com",
        )
        client = httpx.AsyncClient()
        with pytest.raises(ResolveError, match="No server-relative path"):
            await self.resolver.resolve(parsed, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_non_video_uses_value_endpoint(self):
        respx.get(url__startswith="https://contoso.sharepoint.com").mock(
            return_value=httpx.Response(
                200,
                json={
                    "d": {
                        "Name": "report.pdf",
                        "Length": "1024",
                        "ContentType": "application/pdf",
                        "UniqueId": "guid-123",
                    }
                },
            )
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Docs/report.pdf",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/report.pdf",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert "$value" in target.download_url
        assert "download.aspx" not in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_v1_fails_falls_back_to_v2(self):
        # v1 fails
        respx.get(url__regex=r".*_api/web/GetFileByServerRelativeUrl.*").mock(
            return_value=httpx.Response(500, text="Internal error")
        )
        # v2 drive info
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(
            return_value=httpx.Response(
                200,
                json={
                    "webUrl": "https://contoso.sharepoint.com/sites/Team/Shared Documents",
                },
            )
        )
        # v2 item
        respx.get(url__regex=r".*_api/v2\.0/drive/root:.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "video.mp4",
                    "size": 5000,
                    "@content.downloadUrl": "https://blob.windows.net/preauth-url",
                    "file": {"mimeType": "video/mp4"},
                },
            )
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/video.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert target.download_url == "https://blob.windows.net/preauth-url"
        assert target.requires_auth_headers is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_all_fail_falls_back_to_source_url(self):
        # v1 fails
        respx.get(url__regex=r".*_api/web/GetFileByServerRelativeUrl.*").mock(
            return_value=httpx.Response(500)
        )
        # v2 fails
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(return_value=httpx.Response(401))

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/video.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert "download.aspx" in target.download_url
        assert "SourceUrl" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_v2_no_download_url_returns_none(self):
        respx.get(url__regex=r".*_api/web/GetFileByServerRelativeUrl.*").mock(
            return_value=httpx.Response(500)
        )
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(
            return_value=httpx.Response(
                200,
                json={
                    "webUrl": "https://contoso.sharepoint.com/sites/Team/Shared Documents",
                },
            )
        )
        respx.get(url__regex=r".*_api/v2\.0/drive/root:.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "video.mp4",
                    "size": 5000,
                    # No downloadUrl
                },
            )
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/video.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()
        # Falls back to SourceUrl since v2 had no downloadUrl
        assert "SourceUrl" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_v1_video_without_unique_id(self):
        """Video without UniqueId should use SourceUrl-style download."""
        respx.get(url__regex=r".*_api/web/GetFileByServerRelativeUrl.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "d": {
                        "Name": "clip.mp4",
                        "Length": "2048",
                        "ContentType": "video/mp4",
                        # No UniqueId
                    }
                },
            )
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Docs/clip.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/clip.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert "download.aspx" in target.download_url
        assert "SourceUrl" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_v1_500_error_triggers_fallback(self):
        """Non-specific v1 error should fall back to v2/SourceUrl."""
        respx.get(url__regex=r".*_api/web/GetFileByServerRelativeUrl.*").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(
            return_value=httpx.Response(500, text="Error")
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/T/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/T",
            server_relative_path="/sites/T/Shared Documents/v.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert "SourceUrl" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_v2_path_not_under_drive(self):
        """v2 returns None when file path is not under drive root."""
        respx.get(url__regex=r".*_api/web/GetFileByServerRelativeUrl.*").mock(
            return_value=httpx.Response(500)
        )
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(
            return_value=httpx.Response(
                200,
                json={
                    "webUrl": "https://contoso.sharepoint.com/sites/Other/Documents",
                },
            )
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/T/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/T",
            server_relative_path="/sites/T/Shared Documents/v.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        # Falls through to SourceUrl
        assert "SourceUrl" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_v2_graph_download_url(self):
        """v2 with @microsoft.graph.downloadUrl works."""
        respx.get(url__regex=r".*_api/web/GetFileByServerRelativeUrl.*").mock(
            return_value=httpx.Response(500)
        )
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(
            return_value=httpx.Response(
                200,
                json={
                    "webUrl": "https://contoso.sharepoint.com/sites/T/Shared Documents",
                },
            )
        )
        respx.get(url__regex=r".*_api/v2\.0/drive/root:.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "video.mp4",
                    "size": 5000,
                    "@microsoft.graph.downloadUrl": "https://blob.windows.net/graph-url",
                    "file": {"mimeType": "video/mp4"},
                },
            )
        )

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/T/v.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/T",
            server_relative_path="/sites/T/Shared Documents/video.mp4",
        )

        client = httpx.AsyncClient()
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert target.download_url == "https://blob.windows.net/graph-url"
        assert target.requires_auth_headers is False
