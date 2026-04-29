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

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_401_raises_access_denied(self, tmp_path: Path):
        respx.get("https://example.com/file.mp4").mock(return_value=httpx.Response(401))

        target = DownloadTarget(
            metadata=FileMetadata(name="file.mp4", size_bytes=100, content_type="video/mp4"),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        from sp_dl.models import DownloadError

        with pytest.raises(DownloadError):
            await download_file(client, target, tmp_path / "file.mp4")
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_html_instead_of_video_raises(self, tmp_path: Path):
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(
                200,
                content=b"<html>Not a video</html>",
                headers={"Content-Type": "text/html"},
            )
        )

        target = DownloadTarget(
            metadata=FileMetadata(name="file.mp4", size_bytes=5000000, content_type="video/mp4"),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        from sp_dl.models import DownloadError

        with pytest.raises(DownloadError, match="HTML instead"):
            await download_file(client, target, tmp_path / "file.mp4")
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_with_progress_callback(self, tmp_path: Path):
        content = b"x" * 5000
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(200, content=content)
        )

        target = DownloadTarget(
            metadata=FileMetadata(
                name="file.mp4", size_bytes=len(content), content_type="video/mp4"
            ),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        received_bytes = []
        client = httpx.AsyncClient()
        await download_file(
            client,
            target,
            tmp_path / "file.mp4",
            progress_callback=lambda n: received_bytes.append(n),
        )
        await client.aclose()

        assert sum(received_bytes) == len(content)

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_size_mismatch_raises(self, tmp_path: Path):
        content = b"short"
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(200, content=content)
        )

        target = DownloadTarget(
            metadata=FileMetadata(name="file.mp4", size_bytes=99999, content_type="video/mp4"),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        from sp_dl.models import DownloadError

        with pytest.raises(DownloadError, match="Size mismatch"):
            await download_file(client, target, tmp_path / "file.mp4")
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_resume_with_partial_file(self, tmp_path: Path):
        """Resume download from an existing .part file."""
        part_content = b"x" * 100
        remaining = b"y" * 200
        output_path = tmp_path / "file.mp4"
        part_file = _part_path(output_path)
        part_file.write_bytes(part_content)

        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(
                206,
                content=remaining,
                headers={
                    "Content-Length": str(len(remaining)),
                    "Content-Range": "bytes 100-299/300",
                },
            )
        )

        target = DownloadTarget(
            metadata=FileMetadata(name="file.mp4", size_bytes=300, content_type="video/mp4"),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        result = await download_file(client, target, output_path)
        await client.aclose()

        assert result.output_path.exists()
        assert result.output_path.stat().st_size == 300

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_403_raises_access_denied(self, tmp_path: Path):
        respx.get("https://example.com/file.mp4").mock(return_value=httpx.Response(403))

        target = DownloadTarget(
            metadata=FileMetadata(name="file.mp4", size_bytes=100, content_type="video/mp4"),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        from sp_dl.models import DownloadError

        with pytest.raises(DownloadError):
            await download_file(client, target, tmp_path / "file.mp4")
        await client.aclose()

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_with_auth_headers(self, tmp_path: Path):
        """Download that requires auth headers uses client as-is."""
        content = b"authenticated content"
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(200, content=content)
        )

        target = DownloadTarget(
            metadata=FileMetadata(
                name="file.mp4",
                size_bytes=len(content),
                content_type="application/octet-stream",
            ),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=True,
        )

        client = httpx.AsyncClient(headers={"Authorization": "Bearer tok"})
        result = await download_file(client, target, tmp_path / "file.mp4")
        await client.aclose()

        assert result.output_path.read_bytes() == content

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_rate_limited(self, tmp_path: Path):
        """Download with rate limiting completes."""
        content = b"z" * 10000
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(200, content=content)
        )

        target = DownloadTarget(
            metadata=FileMetadata(
                name="file.mp4", size_bytes=len(content), content_type="video/mp4"
            ),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        result = await download_file(
            client,
            target,
            tmp_path / "file.mp4",
            limit_rate=1024 * 1024,  # 1MB/s
        )
        await client.aclose()
        assert result.output_path.exists()

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_server_ignores_range(self, tmp_path: Path):
        """Server returns 200 instead of 206 when Range was sent — restart."""
        output_path = tmp_path / "file.mp4"
        part_file = _part_path(output_path)
        part_file.write_bytes(b"partial")

        full_content = b"full content here"
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(200, content=full_content)
        )

        target = DownloadTarget(
            metadata=FileMetadata(
                name="file.mp4",
                size_bytes=len(full_content),
                content_type="video/mp4",
            ),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        result = await download_file(client, target, output_path)
        await client.aclose()

        assert result.output_path.read_bytes() == full_content

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_429_throttled_then_succeeds(self, tmp_path: Path):
        """Server returns 429 first, then 200 on retry."""
        content = b"finally got it"
        route = respx.get("https://example.com/file.mp4")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, content=content),
        ]

        target = DownloadTarget(
            metadata=FileMetadata(
                name="file.mp4", size_bytes=len(content), content_type="video/mp4"
            ),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        result = await download_file(client, target, tmp_path / "file.mp4")
        await client.aclose()
        assert result.output_path.read_bytes() == content

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_416_range_complete(self, tmp_path: Path):
        """Server returns 416 when file is already complete."""
        output_path = tmp_path / "file.mp4"
        part_file = _part_path(output_path)
        part_file.write_bytes(b"complete file data here")

        respx.get("https://example.com/file.mp4").mock(return_value=httpx.Response(416))

        target = DownloadTarget(
            metadata=FileMetadata(name="file.mp4", size_bytes=22, content_type="video/mp4"),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        result = await download_file(client, target, output_path)
        await client.aclose()
        assert result.output_path.exists()

    @respx.mock
    @pytest.mark.asyncio
    async def test_download_small_content_warning(self, tmp_path: Path):
        """Server returns suspiciously small content for a video."""
        content = b"tiny"  # 4 bytes
        respx.get("https://example.com/file.mp4").mock(
            return_value=httpx.Response(
                200,
                content=content,
                headers={"Content-Length": str(len(content))},
            )
        )

        target = DownloadTarget(
            metadata=FileMetadata(name="file.mp4", size_bytes=50_000_000, content_type="video/mp4"),
            download_url="https://example.com/file.mp4",
            requires_auth_headers=False,
        )

        client = httpx.AsyncClient()
        from sp_dl.models import DownloadError

        with pytest.raises(DownloadError, match="Size mismatch"):
            await download_file(client, target, tmp_path / "file.mp4")
        await client.aclose()
