"""Tests for the download engine."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from sp_dl.downloader.engine import _part_path, download_file, parse_rate_limit
from sp_dl.models import DownloadStatus, DownloadTarget, FileMetadata


class TestParseRateLimit:
    def test_parse_megabytes(self):
        assert parse_rate_limit("5M") == 5 * 1024 * 1024

    def test_parse_kilobytes(self):
        assert parse_rate_limit("500K") == 500 * 1024

    def test_parse_gigabytes(self):
        assert parse_rate_limit("1G") == 1024 * 1024 * 1024

    def test_parse_plain_number(self):
        assert parse_rate_limit("1048576") == 1048576

    def test_parse_none(self):
        assert parse_rate_limit(None) is None

    def test_parse_empty(self):
        assert parse_rate_limit("") is None

    def test_parse_invalid(self):
        assert parse_rate_limit("abc") is None


class TestPartPath:
    def test_part_path(self):
        assert _part_path(Path("video.mp4")) == Path("video.mp4.part")

    def test_part_path_nested(self):
        assert _part_path(Path("/tmp/out/file.mov")) == Path("/tmp/out/file.mov.part")


class TestDownloadFile:
    @respx.mock
    @pytest.mark.asyncio
    async def test_download_basic(self, tmp_path: Path):
        """Test basic download of a small file."""
        content = b"Hello, this is a test file content!" * 100
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(
                200,
                content=content,
                headers={"Content-Length": str(len(content))},
            )
        )

        target = DownloadTarget(
            metadata=FileMetadata(
                name="test.mp4",
                size_bytes=len(content),
                content_type="video/mp4",
            ),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        output_path = tmp_path / "test.mp4"
        client = httpx.AsyncClient()

        result = await download_file(client, target, output_path)
        await client.aclose()

        assert result.output_path.exists()
        assert result.output_path.read_bytes() == content
        assert result.bytes_downloaded == len(content)
        assert target.status == DownloadStatus.COMPLETED

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_no_overwrites(self, tmp_path: Path):
        """Test that no-overwrites skips existing files."""
        output_path = tmp_path / "existing.mp4"
        output_path.write_bytes(b"existing content")

        target = DownloadTarget(
            metadata=FileMetadata(
                name="existing.mp4",
                size_bytes=1000,
                content_type="video/mp4",
            ),
            download_url="https://example.com/file.mp4",
        )

        client = httpx.AsyncClient()
        result = await download_file(client, target, output_path, no_overwrites=True)
        await client.aclose()

        assert result.bytes_downloaded == 0
        assert target.status == DownloadStatus.SKIPPED

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_creates_directories(self, tmp_path: Path):
        """Test that nested output directories are created."""
        content = b"test data"
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(200, content=content)
        )

        target = DownloadTarget(
            metadata=FileMetadata(
                name="file.mp4",
                size_bytes=len(content),
                content_type="video/mp4",
            ),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        output_path = tmp_path / "sub" / "dir" / "file.mp4"
        client = httpx.AsyncClient()

        result = await download_file(client, target, output_path)
        await client.aclose()

        assert result.output_path.exists()
        assert result.output_path.parent.is_dir()
