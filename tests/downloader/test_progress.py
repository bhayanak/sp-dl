"""Tests for download progress bar and size formatting."""

from __future__ import annotations

from sp_dl.downloader.progress import create_download_progress, format_size


class TestFormatSize:
    def test_zero_bytes(self):
        assert format_size(0) == "0 B"

    def test_bytes(self):
        assert format_size(500) == "500 B"

    def test_kilobytes(self):
        result = format_size(1024)
        assert "KB" in result
        assert "1.00" in result

    def test_megabytes(self):
        result = format_size(1024 * 1024 * 5)
        assert "MB" in result
        assert "5.00" in result

    def test_gigabytes(self):
        result = format_size(1024 * 1024 * 1024 * 2)
        assert "GB" in result
        assert "2.00" in result

    def test_terabytes(self):
        result = format_size(1024**4)
        assert "TB" in result

    def test_one_byte(self):
        assert format_size(1) == "1 B"

    def test_large_bytes_below_kb(self):
        assert format_size(1023) == "1023 B"

    def test_exact_1kb(self):
        assert format_size(1024) == "1.00 KB"


class TestCreateDownloadProgress:
    def test_returns_progress_instance(self):
        progress = create_download_progress()
        assert progress is not None
        # Progress should have columns configured
        assert len(progress.columns) > 0
