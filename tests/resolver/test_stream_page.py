"""Tests for stream.aspx page resolver."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from sp_dl.models import (
    DownloadBlockedError,
    ParsedURL,
    ResolveError,
    URLType,
)
from sp_dl.resolver.stream_page import StreamPageResolver

PARSED_STREAM = ParsedURL(
    original_url="https://contoso-my.sharepoint.com/personal/user/_layouts/15/stream.aspx?id=/personal/user/Documents/Recordings/video.mp4",
    url_type=URLType.STREAM_ASPX,
    tenant="contoso",
    tenant_domain="contoso-my.sharepoint.com",
    site_path="/personal/user",
    server_relative_path="/personal/user/Documents/Recordings/video.mp4",
    is_personal=True,
)


def _make_html(
    *,
    g_file_info: dict | None = None,
    video_url: str | None = None,
    title: str = "video.mp4",
) -> str:
    parts = [f"<html><head><title>{title}</title></head><body>"]
    if g_file_info is not None:
        parts.append(f"<script>var g_fileInfo = {json.dumps(g_file_info)};</script>")
    if video_url is not None:
        parts.append(f'<source src="{video_url}" type="video/mp4">')
    parts.append("</body></html>")
    return "".join(parts)


class TestStreamPageResolver:
    def setup_method(self):
        self.resolver = StreamPageResolver()

    def test_can_handle_stream_aspx(self):
        assert self.resolver.can_handle(PARSED_STREAM) is True

    def test_cannot_handle_other(self):
        parsed = ParsedURL(
            original_url="https://x.sharepoint.com/sites/T/Shared Documents/f.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="x",
            tenant_domain="x.sharepoint.com",
        )
        assert self.resolver.can_handle(parsed) is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_download_blocked(self):
        html = _make_html(g_file_info={"isDownloadBlocked": True, "name": "v.mp4"})
        respx.get(PARSED_STREAM.original_url).mock(return_value=httpx.Response(200, text=html))

        async with httpx.AsyncClient() as client:
            with pytest.raises(DownloadBlockedError):
                await self.resolver.resolve(PARSED_STREAM, client)

    @respx.mock
    @pytest.mark.asyncio
    async def test_extracts_video_url(self):
        html = _make_html(video_url="https://cdn.blob.core.windows.net/video.mp4")
        respx.get(PARSED_STREAM.original_url).mock(return_value=httpx.Response(200, text=html))

        async with httpx.AsyncClient() as client:
            target = await self.resolver.resolve(PARSED_STREAM, client)
        assert target.download_url == "https://cdn.blob.core.windows.net/video.mp4"
        assert target.requires_auth_headers is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_extracts_manifest_url(self):
        html = _make_html(video_url="https://media.svc.ms/something.ism/manifest")
        respx.get(PARSED_STREAM.original_url).mock(return_value=httpx.Response(200, text=html))

        async with httpx.AsyncClient() as client:
            target = await self.resolver.resolve(PARSED_STREAM, client)
        assert target.is_manifest is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_fallback_to_download_aspx(self):
        html = _make_html()  # no video URL in HTML
        respx.get(PARSED_STREAM.original_url).mock(return_value=httpx.Response(200, text=html))

        async with httpx.AsyncClient() as client:
            target = await self.resolver.resolve(PARSED_STREAM, client)
        assert "download.aspx" in target.download_url
        assert "SourceUrl=" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_fallback_download_aspx_on_401(self):
        respx.get(PARSED_STREAM.original_url).mock(return_value=httpx.Response(401))

        async with httpx.AsyncClient() as client:
            target = await self.resolver.resolve(PARSED_STREAM, client)
        assert "download.aspx" in target.download_url

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_when_no_path(self):
        parsed = ParsedURL(
            original_url="https://contoso.sharepoint.com/_layouts/15/stream.aspx?id=",
            url_type=URLType.STREAM_ASPX,
            tenant="contoso",
            tenant_domain="contoso.sharepoint.com",
        )
        respx.get(parsed.original_url).mock(return_value=httpx.Response(200, text="<html></html>"))

        async with httpx.AsyncClient() as client:
            with pytest.raises(ResolveError, match="no file path"):
                await self.resolver.resolve(parsed, client)

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_falls_back(self):
        respx.get(PARSED_STREAM.original_url).mock(side_effect=httpx.ConnectError("fail"))

        async with httpx.AsyncClient() as client:
            target = await self.resolver.resolve(PARSED_STREAM, client)
        assert "download.aspx" in target.download_url

    def test_parse_g_file_info_valid(self):
        html = '<script>var g_fileInfo = {"isDownloadBlocked": true, "name": "x.mp4"};</script>'
        result = self.resolver._parse_g_file_info(html)
        assert result["isDownloadBlocked"] is True

    def test_parse_g_file_info_invalid_json(self):
        html = "<script>var g_fileInfo = {not valid json};</script>"
        assert self.resolver._parse_g_file_info(html) is None

    def test_parse_g_file_info_missing(self):
        assert self.resolver._parse_g_file_info("<html></html>") is None

    def test_extract_metadata_with_duration(self):
        html = (
            "<html><head><title>My Video</title></head><body>"
            '<script>"duration": 12345</script></body></html>'
        )
        meta = self.resolver._extract_metadata(html, PARSED_STREAM)
        assert meta.video_info is not None
        assert meta.video_info.duration_ms == 12345

    def test_extract_metadata_default_name(self):
        html = "<html><head></head><body></body></html>"
        meta = self.resolver._extract_metadata(html, PARSED_STREAM)
        assert meta.name == "video.mp4"

    def test_default_metadata(self):
        meta = self.resolver._default_metadata(PARSED_STREAM)
        assert meta.name == "video.mp4"
        assert meta.content_type == "video/mp4"

    def test_extract_from_json_config_data_attr(self):
        html = '<html><body><div data-mediasources=\'[{"url": "https://cdn.example.com/v.mp4"}]\'></div></body></html>'
        url = self.resolver._extract_from_json_config(html)
        assert url == "https://cdn.example.com/v.mp4"

    def test_extract_from_json_config_script(self):
        html = (
            '<html><body><script>{"url": "https://cdn.example.com/file.mp4"}</script></body></html>'
        )
        url = self.resolver._extract_from_json_config(html)
        assert url == "https://cdn.example.com/file.mp4"

    def test_extract_from_json_config_no_match(self):
        html = "<html><body><script>var x = 42;</script></body></html>"
        assert self.resolver._extract_from_json_config(html) is None
