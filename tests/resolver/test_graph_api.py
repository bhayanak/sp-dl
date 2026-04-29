"""Tests for Graph API resolver."""

from __future__ import annotations

import httpx
import pytest
import respx

from sp_dl.models import AccessDeniedError, ParsedURL, ResolveError, URLType
from sp_dl.resolver.graph_api import GraphAPIResolver

PARSED_DIRECT = ParsedURL(
    original_url="https://contoso.sharepoint.com/sites/Team/Docs/v.mp4",
    url_type=URLType.DIRECT_PATH,
    tenant="contoso",
    tenant_domain="contoso.sharepoint.com",
    site_path="/sites/Team",
    server_relative_path="/sites/Team/Shared Documents/Recordings/video.mp4",
)

PARSED_DOC = ParsedURL(
    original_url="https://contoso.sharepoint.com/sites/T/_layouts/15/Doc.aspx?sourcedoc={guid-123}",
    url_type=URLType.DOC_ASPX,
    tenant="contoso",
    tenant_domain="contoso.sharepoint.com",
    site_path="/sites/T",
    source_doc_guid="guid-123",
)


class TestGraphAPIResolver:
    def setup_method(self):
        self.resolver = GraphAPIResolver()

    def test_can_handle_direct_path(self):
        assert self.resolver.can_handle(PARSED_DIRECT) is True

    def test_can_handle_doc_aspx(self):
        assert self.resolver.can_handle(PARSED_DOC) is True

    def test_cannot_handle_sharing_link(self):
        parsed = ParsedURL(
            original_url="https://x.sharepoint.com/:v:/s/T/abc",
            url_type=URLType.SHARING_LINK,
            tenant="x",
            tenant_domain="x.sharepoint.com",
        )
        assert self.resolver.can_handle(parsed) is False

    @pytest.mark.asyncio
    async def test_no_auth_header_raises(self):
        client = httpx.AsyncClient()
        with pytest.raises(ResolveError, match="OAuth token"):
            await self.resolver.resolve(PARSED_DIRECT, client)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_no_path_or_guid_raises(self):
        parsed = ParsedURL(
            original_url="https://x.sharepoint.com/...",
            url_type=URLType.DIRECT_PATH,
            tenant="x",
            tenant_domain="x.sharepoint.com",
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        with pytest.raises(ResolveError, match="needs either a path or GUID"):
            await self.resolver.resolve(parsed, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_path(self, graph_driveitem_response):
        # Mock both site lookup and drive item lookup with a single route
        respx.get(url__startswith="https://graph.microsoft.com/v1.0/sites/").mock(
            side_effect=[
                httpx.Response(200, json={"id": "site-id-123"}),
                httpx.Response(200, json=graph_driveitem_response),
            ]
        )

        client = httpx.AsyncClient(headers={"Authorization": "Bearer test-token"})
        target = await self.resolver.resolve(PARSED_DIRECT, client)
        await client.aclose()

        assert target.metadata.name == "Q3 All-Hands Recording.mp4"
        assert target.metadata.size_bytes == 1524629504
        assert target.metadata.video_info is not None
        assert target.metadata.video_info.width == 1920
        assert target.requires_auth_headers is False  # pre-auth URL

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_path_401(self):
        respx.get(url__startswith="https://graph.microsoft.com").mock(
            return_value=httpx.Response(401)
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer bad"})
        with pytest.raises(AccessDeniedError):
            await self.resolver.resolve(PARSED_DIRECT, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_path_403(self):
        respx.get(url__startswith="https://graph.microsoft.com").mock(
            return_value=httpx.Response(403)
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        with pytest.raises(AccessDeniedError):
            await self.resolver.resolve(PARSED_DIRECT, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_path_site_error(self):
        respx.get(url__startswith="https://graph.microsoft.com").mock(
            return_value=httpx.Response(500)
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        with pytest.raises(ResolveError, match="Failed to resolve site"):
            await self.resolver.resolve(PARSED_DIRECT, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_path_item_404(self):
        respx.get(url__startswith="https://graph.microsoft.com").mock(
            side_effect=[
                httpx.Response(200, json={"id": "sid"}),
                httpx.Response(404),
            ]
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        with pytest.raises(ResolveError, match="File not found via Graph"):
            await self.resolver.resolve(PARSED_DIRECT, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_guid_success(self, graph_driveitem_response):
        respx.get(url__startswith="https://graph.microsoft.com").mock(
            side_effect=[
                httpx.Response(200, json={"id": "sid2"}),
                httpx.Response(200, json={"value": [graph_driveitem_response]}),
            ]
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        target = await self.resolver.resolve(PARSED_DOC, client)
        await client.aclose()
        assert target.metadata.name == "Q3 All-Hands Recording.mp4"

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_guid_no_results(self):
        respx.get(url__startswith="https://graph.microsoft.com").mock(
            side_effect=[
                httpx.Response(200, json={"id": "sid"}),
                httpx.Response(200, json={"value": []}),
            ]
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        with pytest.raises(ResolveError, match="No file found"):
            await self.resolver.resolve(PARSED_DOC, client)
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_by_guid_search_fails(self):
        respx.get(url__startswith="https://graph.microsoft.com").mock(
            side_effect=[
                httpx.Response(200, json={"id": "sid"}),
                httpx.Response(500),
            ]
        )
        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        with pytest.raises(ResolveError, match="Search failed"):
            await self.resolver.resolve(PARSED_DOC, client)
        await client.aclose()

    def test_parse_drive_item_no_download_url(self):
        item = {"name": "file.mp4", "size": 100}
        with pytest.raises(ResolveError, match="No download URL"):
            self.resolver._parse_drive_item(item)

    def test_parse_drive_item_with_content_fallback(self):
        item = {
            "name": "file.mp4",
            "size": 100,
            "id": "item-id",
            "parentReference": {"driveId": "drive-id"},
        }
        target = self.resolver._parse_drive_item(item)
        assert "content" in target.download_url
        assert "drive-id" in target.download_url

    def test_parse_drive_item_with_video_info(self, graph_driveitem_response):
        target = self.resolver._parse_drive_item(graph_driveitem_response)
        assert target.metadata.video_info is not None
        assert target.metadata.video_info.duration_ms == 3600000
        assert target.metadata.video_info.width == 1920
        assert target.metadata.created_by == "John Smith"
