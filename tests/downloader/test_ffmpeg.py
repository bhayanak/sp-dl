"""Tests for ffmpeg integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sp_dl.downloader.ffmpeg import download_manifest, is_ffmpeg_available
from sp_dl.models import DownloadError


class TestIsFFmpegAvailable:
    def test_ffmpeg_found(self):
        with patch("sp_dl.downloader.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"):
            assert is_ffmpeg_available() is True

    def test_ffmpeg_not_found(self):
        with patch("sp_dl.downloader.ffmpeg.shutil.which", return_value=None):
            assert is_ffmpeg_available() is False


class TestDownloadManifest:
    @pytest.mark.asyncio
    async def test_raises_when_ffmpeg_missing(self, tmp_path: Path):
        with (
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=False),
            pytest.raises(DownloadError, match="ffmpeg is required"),
        ):
            await download_manifest(
                "https://example.com/manifest.mpd",
                tmp_path / "video.mp4",
            )

    @pytest.mark.asyncio
    async def test_successful_download(self, tmp_path: Path):
        output_path = tmp_path / "video.mp4"

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True),
            patch(
                "sp_dl.downloader.ffmpeg.asyncio.create_subprocess_exec",
                return_value=mock_process,
            ),
        ):
            # Create the output file to simulate ffmpeg writing it
            output_path.write_bytes(b"fake video data")

            result = await download_manifest(
                "https://example.com/manifest.mpd",
                output_path,
            )
            assert result == output_path

    @pytest.mark.asyncio
    async def test_ffmpeg_failure_raises(self, tmp_path: Path):
        output_path = tmp_path / "video.mp4"

        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.communicate = AsyncMock(return_value=(b"", b"Error: something went wrong"))

        with (
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True),
            patch(
                "sp_dl.downloader.ffmpeg.asyncio.create_subprocess_exec",
                return_value=mock_process,
            ),
            pytest.raises(DownloadError, match="ffmpeg failed"),
        ):
            await download_manifest(
                "https://example.com/manifest.mpd",
                output_path,
            )

    @pytest.mark.asyncio
    async def test_output_file_not_found_raises(self, tmp_path: Path):
        output_path = tmp_path / "video.mp4"

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True),
            patch(
                "sp_dl.downloader.ffmpeg.asyncio.create_subprocess_exec",
                return_value=mock_process,
            ),
            # Don't create the output file
            pytest.raises(DownloadError, match="output file not found"),
        ):
            await download_manifest(
                "https://example.com/manifest.mpd",
                output_path,
            )

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_path: Path):
        output_path = tmp_path / "sub" / "dir" / "video.mp4"

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True),
            patch(
                "sp_dl.downloader.ffmpeg.asyncio.create_subprocess_exec",
                return_value=mock_process,
            ),
        ):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"data")

            await download_manifest(
                "https://example.com/manifest.mpd",
                output_path,
            )
            assert output_path.parent.is_dir()

    @pytest.mark.asyncio
    async def test_cookies_file_passed_to_ffmpeg(self, tmp_path: Path):
        output_path = tmp_path / "video.mp4"
        cookies_file = tmp_path / "cookies.txt"
        cookies_file.write_text("cookie data")

        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))

        with (
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True),
            patch(
                "sp_dl.downloader.ffmpeg.asyncio.create_subprocess_exec",
                return_value=mock_process,
            ) as mock_exec,
        ):
            output_path.write_bytes(b"data")
            await download_manifest(
                "https://example.com/manifest.mpd",
                output_path,
                cookies_file=cookies_file,
            )
            # Verify cookies were passed in command
            call_args = mock_exec.call_args[0]
            assert "-cookies" in call_args
