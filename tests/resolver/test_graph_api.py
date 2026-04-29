"""Tests for Graph API resolver."""

from __future__ import annotations

import httpx
import pytest
import respx

from sp_dl.models import ParsedURL, URLType
from sp_dl.resolver.graph_api import GraphAPIResolver


class TestGraphAPIResolver:
    def setup_method(self):
        self.resolver = GraphAPIResolver()

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

        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/sites/Team/Shared Documents/vid.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
            site_path="/sites/Team",
            server_relative_path="/sites/Team/Shared Documents/Recordings/vid.mp4",
        )

        client = httpx.AsyncClient(headers={"Authorization": "Bearer test-token"})
        target = await self.resolver.resolve(parsed, client)
        await client.aclose()

        assert target.metadata.name == "Q3 All-Hands Recording.mp4"
        assert target.metadata.size_bytes == 1524629504
        assert target.metadata.video_info is not None
        assert target.metadata.video_info.width == 1920
        assert target.requires_auth_headers is False  # pre-auth URL
