"""Tests for resolve_download_target orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from sp_dl.models import (
    AccessDeniedError,
    DownloadBlockedError,
    DownloadTarget,
    FileMetadata,
    FileNotFoundOnServerError,
    ParsedURL,
    ResolveError,
    URLType,
)
from sp_dl.resolver.base import resolve_download_target


def _make_target(name: str = "file.mp4") -> DownloadTarget:
    return DownloadTarget(
        metadata=FileMetadata(name=name, size_bytes=100, content_type="video/mp4"),
        download_url=f"https://example.com/{name}",
    )


PARSED_STREAM = ParsedURL(
    original_url="https://contoso-my.sharepoint.com/personal/user/_layouts/15/stream.aspx?id=/personal/user/Documents/v.mp4",
    url_type=URLType.STREAM_ASPX,
    tenant="contoso",
    tenant_domain="contoso-my.sharepoint.com",
    site_path="/personal/user",
    server_relative_path="/personal/user/Documents/v.mp4",
    is_personal=True,
)

PARSED_SHARING = ParsedURL(
    original_url="https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFg",
    url_type=URLType.SHARING_LINK,
    tenant="contoso",
    tenant_domain="contoso.sharepoint.com",
    sharing_token="EaBcDeFg",
)

PARSED_DIRECT = ParsedURL(
    original_url="https://contoso.sharepoint.com/sites/T/Shared Documents/v.mp4",
    url_type=URLType.DIRECT_PATH,
    tenant="contoso",
    tenant_domain="contoso.sharepoint.com",
    site_path="/sites/T",
    server_relative_path="/sites/T/Shared Documents/v.mp4",
)

PARSED_DOC = ParsedURL(
    original_url="https://contoso.sharepoint.com/sites/T/_layouts/15/Doc.aspx?sourcedoc={abc-123}",
    url_type=URLType.DOC_ASPX,
    tenant="contoso",
    tenant_domain="contoso.sharepoint.com",
    site_path="/sites/T",
    source_doc_guid="abc-123",
)


class TestResolveDownloadTarget:
    @pytest.mark.asyncio
    async def test_stream_aspx_first_resolver_succeeds(self):
        target = _make_target()
        with patch(
            "sp_dl.resolver.stream_page.StreamPageResolver.resolve",
            new_callable=AsyncMock,
            return_value=target,
        ):
            async with httpx.AsyncClient() as client:
                result = await resolve_download_target(PARSED_STREAM, client)
            assert result is target

    @pytest.mark.asyncio
    async def test_stream_aspx_download_blocked_propagates(self):
        with patch(
            "sp_dl.resolver.stream_page.StreamPageResolver.resolve",
            new_callable=AsyncMock,
            side_effect=DownloadBlockedError("blocked"),
        ):
            async with httpx.AsyncClient() as client:
                with pytest.raises(DownloadBlockedError):
                    await resolve_download_target(PARSED_STREAM, client)

    @pytest.mark.asyncio
    async def test_stream_aspx_falls_back_to_sp_rest(self):
        target = _make_target()
        with (
            patch(
                "sp_dl.resolver.stream_page.StreamPageResolver.resolve",
                new_callable=AsyncMock,
                side_effect=ResolveError("nope"),
            ),
            patch(
                "sp_dl.resolver.sp_rest.SharePointRESTResolver.resolve",
                new_callable=AsyncMock,
                return_value=target,
            ),
        ):
            async with httpx.AsyncClient() as client:
                result = await resolve_download_target(PARSED_STREAM, client)
            assert result is target

    @pytest.mark.asyncio
    async def test_stream_aspx_access_denied_falls_through(self):
        target = _make_target()
        with (
            patch(
                "sp_dl.resolver.stream_page.StreamPageResolver.resolve",
                new_callable=AsyncMock,
                side_effect=AccessDeniedError("denied"),
            ),
            patch(
                "sp_dl.resolver.sp_rest.SharePointRESTResolver.resolve",
                new_callable=AsyncMock,
                return_value=target,
            ),
        ):
            async with httpx.AsyncClient() as client:
                result = await resolve_download_target(PARSED_STREAM, client)
            assert result is target

    @pytest.mark.asyncio
    async def test_all_resolvers_fail_raises(self):
        with (
            patch(
                "sp_dl.resolver.stream_page.StreamPageResolver.resolve",
                new_callable=AsyncMock,
                side_effect=ResolveError("fail1"),
            ),
            patch(
                "sp_dl.resolver.sp_rest.SharePointRESTResolver.resolve",
                new_callable=AsyncMock,
                side_effect=ResolveError("fail2"),
            ),
            patch(
                "sp_dl.resolver.graph_api.GraphAPIResolver.resolve",
                new_callable=AsyncMock,
                side_effect=ResolveError("fail3"),
            ),
        ):
            async with httpx.AsyncClient() as client:
                with pytest.raises(ResolveError, match="All resolution strategies failed"):
                    await resolve_download_target(PARSED_STREAM, client)

    @pytest.mark.asyncio
    async def test_sharing_link_uses_sharing_resolver(self):
        target = _make_target()
        with patch(
            "sp_dl.resolver.sharing.SharingLinkResolver.resolve",
            new_callable=AsyncMock,
            return_value=target,
        ):
            async with httpx.AsyncClient() as client:
                result = await resolve_download_target(PARSED_SHARING, client)
            assert result is target

    @pytest.mark.asyncio
    async def test_doc_aspx_uses_graph_api_first(self):
        target = _make_target()
        with patch(
            "sp_dl.resolver.graph_api.GraphAPIResolver.resolve",
            new_callable=AsyncMock,
            return_value=target,
        ):
            async with httpx.AsyncClient() as client:
                result = await resolve_download_target(PARSED_DOC, client)
            assert result is target

    @pytest.mark.asyncio
    async def test_direct_path_uses_sp_rest_first(self):
        target = _make_target()
        with patch(
            "sp_dl.resolver.sp_rest.SharePointRESTResolver.resolve",
            new_callable=AsyncMock,
            return_value=target,
        ):
            async with httpx.AsyncClient() as client:
                result = await resolve_download_target(PARSED_DIRECT, client)
            assert result is target

    @pytest.mark.asyncio
    async def test_file_not_found_falls_through(self):
        target = _make_target()
        with (
            patch(
                "sp_dl.resolver.sp_rest.SharePointRESTResolver.resolve",
                new_callable=AsyncMock,
                side_effect=FileNotFoundOnServerError("not found"),
            ),
            patch(
                "sp_dl.resolver.graph_api.GraphAPIResolver.resolve",
                new_callable=AsyncMock,
                return_value=target,
            ),
        ):
            async with httpx.AsyncClient() as client:
                result = await resolve_download_target(PARSED_DIRECT, client)
            assert result is target
