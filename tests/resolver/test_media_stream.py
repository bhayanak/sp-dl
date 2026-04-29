"""Tests for media stream resolver (download-blocked video fallback)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from sp_dl.models import (
    ParsedURL,
    ResolveError,
    URLType,
)
from sp_dl.resolver.media_stream import MediaStreamResolver

PARSED_STREAM = ParsedURL(
    original_url="https://contoso-my.sharepoint.com/personal/user/_layouts/15/stream.aspx?id=/personal/user/Documents/Recordings/video.mp4",
    url_type=URLType.STREAM_ASPX,
    tenant="contoso",
    tenant_domain="contoso-my.sharepoint.com",
    site_path="/personal/user",
    server_relative_path="/personal/user/Documents/Recordings/video.mp4",
    is_personal=True,
)

G_FILE_INFO = {
    "name": "video.mp4",
    "size": 100000,
    ".spItemUrl": "https://contoso-my.sharepoint.com/_api/v2.0/drives/drv123/items/itm456",
    "VroomItemId": "itm456",
    ".transformUrl": "https://southcentralus1-mediap.svc.ms/transform/video?provider=spo&farmid=191780&cs=fFNQTw",
    "isDownloadBlocked": True,
    "MediaServiceFastMetadata": json.dumps({"media": {"duration": 60000}}),
}


def _stream_html(file_info: dict | None = None) -> str:
    info = file_info or G_FILE_INFO
    return f"<html><script>var g_fileInfo = {json.dumps(info)};</script></html>"


class TestMediaStreamResolver:
    def test_can_handle(self):
        resolver = MediaStreamResolver()
        assert resolver.can_handle(PARSED_STREAM) is True

    def test_cannot_handle_other_type(self):
        resolver = MediaStreamResolver()
        parsed = ParsedURL(
            original_url="https://x.sharepoint.com/f.mp4",
            url_type=URLType.DIRECT_PATH,
            tenant="x",
            tenant_domain="x.sharepoint.com",
        )
        assert resolver.can_handle(parsed) is False

    @pytest.mark.asyncio
    async def test_raises_without_oauth_token(self):
        resolver = MediaStreamResolver()
        async with httpx.AsyncClient() as client:
            with pytest.raises(ResolveError, match="OAuth2 token required"):
                await resolver.resolve(PARSED_STREAM, client)

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_via_g_file_info(self):
        resolver = MediaStreamResolver(oauth_token="test-jwt-token")
        respx.get(PARSED_STREAM.original_url).mock(
            return_value=httpx.Response(200, text=_stream_html())
        )

        async with httpx.AsyncClient() as client:
            target = await resolver.resolve(PARSED_STREAM, client)

        assert target.is_manifest is True
        assert target.requires_auth_headers is False
        assert "videomanifest" in target.download_url
        assert "test-jwt-token" in target.download_url
        assert "drv123" in target.download_url
        assert "itm456" in target.download_url
        assert target.metadata.name == "video.mp4"
        assert target.metadata.size_bytes == 100000
        assert target.metadata.video_info is not None
        assert target.metadata.video_info.duration_ms == 60000

    @respx.mock
    @pytest.mark.asyncio
    async def test_resolve_via_rest_api_fallback(self):
        resolver = MediaStreamResolver(oauth_token="test-jwt-token")

        # g_fileInfo unavailable
        respx.get(PARSED_STREAM.original_url).mock(return_value=httpx.Response(401))

        # REST API fallback
        respx.get("https://contoso-my.sharepoint.com/personal/user/_api/v2.0/drive").mock(
            return_value=httpx.Response(
                200,
                json={
                    "webUrl": "https://contoso-my.sharepoint.com/personal/user/Documents",
                },
            )
        )
        respx.get(url__regex=r".*_api/v2\.0/drive/root:.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "rest-item-123",
                    "name": "video.mp4",
                    "size": 50000,
                    "parentReference": {"driveId": "rest-drive-456"},
                },
            )
        )

        async with httpx.AsyncClient() as client:
            target = await resolver.resolve(PARSED_STREAM, client)

        assert target.is_manifest is True
        assert "rest-drive-456" in target.download_url
        assert "rest-item-123" in target.download_url
        assert target.metadata.name == "video.mp4"

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_when_both_methods_fail(self):
        resolver = MediaStreamResolver(oauth_token="test-jwt-token")
        respx.get(PARSED_STREAM.original_url).mock(return_value=httpx.Response(401))
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(return_value=httpx.Response(401))

        async with httpx.AsyncClient() as client:
            with pytest.raises(ResolveError, match="Could not extract"):
                await resolver.resolve(PARSED_STREAM, client)

    def test_set_oauth_token(self):
        resolver = MediaStreamResolver()
        assert resolver._oauth_token is None
        resolver.set_oauth_token("new-token")
        assert resolver._oauth_token == "new-token"

    def test_parse_file_info_valid(self):
        resolver = MediaStreamResolver()
        html = _stream_html()
        result = resolver._parse_file_info(html)
        assert result is not None
        assert result["drive_id"] == "drv123"
        assert result["item_id"] == "itm456"
        assert result["transform_host"] == "southcentralus1-mediap.svc.ms"
        assert result["farmid"] == "191780"
        assert result["name"] == "video.mp4"

    def test_parse_file_info_missing_ids(self):
        resolver = MediaStreamResolver()
        html = f"<script>var g_fileInfo = {json.dumps({'name': 'x.mp4'})};</script>"
        assert resolver._parse_file_info(html) is None

    def test_parse_file_info_no_script(self):
        resolver = MediaStreamResolver()
        assert resolver._parse_file_info("<html></html>") is None

    def test_parse_file_info_bad_json(self):
        resolver = MediaStreamResolver()
        html = "<script>var g_fileInfo = {bad json};</script>"
        assert resolver._parse_file_info(html) is None

    def test_parse_file_info_no_transform_url(self):
        resolver = MediaStreamResolver()
        info = {
            ".spItemUrl": "https://x.sharepoint.com/_api/v2.0/drives/d1/items/i1",
            "VroomItemId": "i1",
            "name": "v.mp4",
        }
        html = f"<script>var g_fileInfo = {json.dumps(info)};</script>"
        result = resolver._parse_file_info(html)
        assert result is not None
        assert result["transform_host"] == "southcentralus1-mediap.svc.ms"  # default

    def test_parse_file_info_bad_media_metadata(self):
        resolver = MediaStreamResolver()
        info = {
            ".spItemUrl": "https://x.sharepoint.com/_api/v2.0/drives/d1/items/i1",
            "VroomItemId": "i1",
            "name": "v.mp4",
            "MediaServiceFastMetadata": "not json",
        }
        html = f"<script>var g_fileInfo = {json.dumps(info)};</script>"
        result = resolver._parse_file_info(html)
        assert result is not None
        assert result["duration_ms"] is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_rest_api_no_server_path(self):
        resolver = MediaStreamResolver(oauth_token="tok")
        parsed = ParsedURL(
            original_url="https://x.sharepoint.com/_layouts/15/stream.aspx?id=",
            url_type=URLType.STREAM_ASPX,
            tenant="x",
            tenant_domain="x.sharepoint.com",
            site_path="/sites/T",
        )
        result = await resolver._extract_from_rest_api(parsed, httpx.AsyncClient())
        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_rest_api_path_mismatch(self):
        resolver = MediaStreamResolver(oauth_token="tok")
        respx.get(url__regex=r".*_api/v2\.0/drive$").mock(
            return_value=httpx.Response(
                200, json={"webUrl": "https://x.sharepoint.com/sites/T/OtherLib"}
            )
        )

        async with httpx.AsyncClient() as client:
            result = await resolver._extract_from_rest_api(PARSED_STREAM, client)
        assert result is None
