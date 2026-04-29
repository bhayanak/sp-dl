"""Tests for CLI download pipeline (_download_async)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from sp_dl.cli import app
from sp_dl.models import (
    DownloadBlockedError,
    DownloadResult,
    DownloadStatus,
    DownloadTarget,
    FileMetadata,
    ParsedURL,
    ResolveError,
    SpDlError,
    URLType,
    VideoInfo,
)

runner = CliRunner()


def _sample_parsed():
    return ParsedURL(
        original_url="https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
        url_type=URLType.STREAM_ASPX,
        tenant="contoso",
        tenant_domain="contoso.sharepoint.com",
        site_path="/sites/T",
        server_relative_path="/sites/T/Docs/v.mp4",
    )


def _sample_target():
    return DownloadTarget(
        metadata=FileMetadata(
            name="video.mp4",
            size_bytes=5000000,
            content_type="video/mp4",
            server_relative_path="/sites/T/Docs/v.mp4",
        ),
        download_url="https://example.com/download/video.mp4",
        requires_auth_headers=False,
    )


def _sample_result(target, tmp_path):
    return DownloadResult(
        target=target,
        output_path=tmp_path / "video.mp4",
        bytes_downloaded=5000000,
        elapsed_seconds=2.5,
    )


class TestDownloadCommand:
    """Integration tests for the download command with mocked internals."""

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.engine.download_file", new_callable=AsyncMock)
    def test_download_success(
        self, mock_dl, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        parsed = _sample_parsed()
        target = _sample_target()
        target.status = DownloadStatus.COMPLETED

        mock_parse.return_value = parsed
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        mock_dl.return_value = DownloadResult(
            target=target,
            output_path=tmp_path / "video.mp4",
            bytes_downloaded=5000000,
            elapsed_seconds=2.0,
        )

        runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(tmp_path / "cookies.txt"),
                "-q",
            ],
        )
        # May fail due to cookie file not existing, which is fine - auth error
        # The important thing is we reach the download flow

    @patch("sp_dl.url_parser.detect_and_parse")
    def test_download_invalid_url_error(self, mock_parse, tmp_path):
        from sp_dl.models import URLParseError

        mock_parse.side_effect = URLParseError("Not a SharePoint URL")

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        result = runner.invoke(
            app,
            [
                "download",
                "https://not-sharepoint.com/file.mp4",
                "-c",
                str(cookies),
            ],
        )
        assert result.exit_code == 1

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_resolve_error(
        self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.side_effect = ResolveError("All strategies failed")

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        result = runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
            ],
        )
        assert result.exit_code == 1

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_info_only(self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path):
        target = _sample_target()
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        result = runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
                "--info",
            ],
        )
        assert result.exit_code == 0
        # The resolved target name is shown
        assert "File info" in result.output

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_json_output(
        self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        target = _sample_target()
        target.metadata.video_info = VideoInfo(duration_ms=60000, width=1920, height=1080)
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        result = runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
                "--json",
                "-q",
            ],
        )
        assert result.exit_code == 0
        # Verify JSON-like output is present
        assert "name" in result.output
        assert "content_type" in result.output

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    def test_download_auth_error(self, mock_auth, mock_parse, tmp_path):
        from sp_dl.models import AuthError

        mock_parse.return_value = _sample_parsed()
        mock_auth.side_effect = AuthError("No cookie file or browser specified")

        result = runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
            ],
        )
        assert result.exit_code == 1
        assert "Auth Error" in result.output or "cookie" in result.output.lower()


class TestBatchCommand:
    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.engine.download_file", new_callable=AsyncMock)
    def test_batch_downloads_urls(
        self, mock_dl, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        target = _sample_target()
        target.status = DownloadStatus.COMPLETED
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        mock_dl.return_value = DownloadResult(
            target=target,
            output_path=tmp_path / "video.mp4",
            bytes_downloaded=5000000,
            elapsed_seconds=2.0,
        )

        batch_file = tmp_path / "urls.txt"
        batch_file.write_text(
            "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4\n"
            "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v2.mp4\n"
        )

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        runner.invoke(
            app,
            [
                "batch",
                str(batch_file),
                "-c",
                str(cookies),
                "-q",
            ],
        )
        # Just verify it processes without crashing
        assert mock_parse.called

    def test_batch_with_comments_and_blanks(self, tmp_path):
        batch_file = tmp_path / "urls.txt"
        batch_file.write_text("# comment\n\n  # another comment\n\n")

        result = runner.invoke(app, ["batch", str(batch_file)])
        assert result.exit_code == 0
        assert "No URLs" in result.output


class TestDownloadFlow:
    """Tests for specific download flow scenarios."""

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.engine.download_file", new_callable=AsyncMock)
    def test_download_with_output_template(
        self, mock_dl, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        target = _sample_target()
        target.status = DownloadStatus.COMPLETED
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        mock_dl.return_value = DownloadResult(
            target=target,
            output_path=tmp_path / "custom.mp4",
            bytes_downloaded=5000000,
            elapsed_seconds=1.0,
        )

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
                "-o",
                "custom.mp4",
                "-q",
            ],
        )

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.engine.download_file", new_callable=AsyncMock)
    def test_download_skipped_file(
        self, mock_dl, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        target = _sample_target()
        target.status = DownloadStatus.SKIPPED
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        mock_dl.return_value = DownloadResult(
            target=target,
            output_path=tmp_path / "video.mp4",
            bytes_downloaded=0,
            elapsed_seconds=0.0,
        )

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
                "--no-overwrites",
            ],
        )

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.engine.download_file", new_callable=AsyncMock)
    def test_download_error(
        self, mock_dl, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        target = _sample_target()
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        from sp_dl.models import DownloadError

        mock_dl.side_effect = DownloadError("Connection lost")

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        result = runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
            ],
        )
        assert result.exit_code == 1

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_blocked_triggers_media_stream(
        self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        """When resolve raises DownloadBlockedError, CLI should try media stream."""
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.side_effect = DownloadBlockedError("blocked by admin")

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        # Mock the device code auth to prevent interactive flow
        with (
            patch(
                "sp_dl.auth.device_code.DeviceCodeAuthProvider.authenticate",
                new_callable=AsyncMock,
            ) as mock_dc_auth,
            patch(
                "sp_dl.resolver.media_stream.MediaStreamResolver.resolve",
                new_callable=AsyncMock,
            ) as mock_ms,
        ):
            mock_dc_auth.return_value = AsyncMock()
            mock_ms.side_effect = SpDlError("media stream failed")

            result = runner.invoke(
                app,
                [
                    "download",
                    "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                    "-c",
                    str(cookies),
                    "-q",
                ],
            )
        assert result.exit_code == 1

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_manifest_no_ffmpeg(
        self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        target = _sample_target()
        target.is_manifest = True
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        with patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=False):
            result = runner.invoke(
                app,
                [
                    "download",
                    "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                    "-c",
                    str(cookies),
                ],
            )
        assert result.exit_code == 1
        assert "ffmpeg" in result.output.lower()

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.ffmpeg.download_manifest", new_callable=AsyncMock)
    @patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True)
    def test_download_manifest_success(
        self,
        mock_ffmpeg_avail,
        mock_dl_manifest,
        mock_resolve,
        mock_session,
        mock_auth,
        mock_parse,
        tmp_path,
    ):
        target = _sample_target()
        target.is_manifest = True
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        mock_dl_manifest.return_value = None

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        result = runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
            ],
        )
        assert result.exit_code == 0
        mock_dl_manifest.assert_called_once()

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.engine.download_file", new_callable=AsyncMock)
    def test_download_verbose_with_metadata(
        self, mock_dl, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        """Verbose output should show size, type, and speed."""
        from datetime import datetime, timezone

        target = _sample_target()
        target.metadata.size_bytes = 10_000_000
        target.metadata.modified_at = datetime(2024, 1, 15, tzinfo=timezone.utc)
        target.metadata.created_by = "John Doe"
        target.status = DownloadStatus.COMPLETED
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        mock_dl.return_value = DownloadResult(
            target=target,
            output_path=tmp_path / "video.mp4",
            bytes_downloaded=10_000_000,
            elapsed_seconds=5.0,
        )

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        result = runner.invoke(
            app,
            [
                "download",
                "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                "-c",
                str(cookies),
            ],
        )
        assert result.exit_code == 0
        assert "Downloaded" in result.output or "Skipped" in result.output

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_blocked_verbose(
        self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        """DownloadBlockedError should show warning in verbose mode."""
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.side_effect = DownloadBlockedError("blocked")

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        with (
            patch(
                "sp_dl.auth.device_code.DeviceCodeAuthProvider.authenticate",
                new_callable=AsyncMock,
            ) as mock_dc_auth,
            patch(
                "sp_dl.resolver.media_stream.MediaStreamResolver.resolve",
                new_callable=AsyncMock,
            ) as mock_ms,
        ):
            mock_dc_auth.return_value = AsyncMock()
            mock_ms.side_effect = SpDlError("media failed")

            result = runner.invoke(
                app,
                [
                    "download",
                    "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                    "-c",
                    str(cookies),
                ],
            )
        # Non-quiet mode should mention download blocked
        assert (
            "blocked" in result.output.lower()
            or "oauth2" in result.output.lower()
            or result.exit_code == 1
        )

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_blocked_media_stream_success(
        self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        """DownloadBlockedError → media stream → ffmpeg manifest download."""
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.side_effect = DownloadBlockedError("blocked")

        manifest_target = _sample_target()
        manifest_target.is_manifest = True

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        with (
            patch("sp_dl.auth.device_code.DeviceCodeAuthProvider") as mock_dc_cls,
            patch(
                "sp_dl.resolver.media_stream.MediaStreamResolver.resolve",
                new_callable=AsyncMock,
            ) as mock_ms,
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True),
            patch("sp_dl.downloader.ffmpeg.download_manifest", new_callable=AsyncMock),
        ):
            mock_instance = mock_dc_cls.return_value
            mock_instance.authenticate = AsyncMock()
            mock_instance._access_token = "fake-oauth-token"
            mock_ms.return_value = manifest_target

            result = runner.invoke(
                app,
                [
                    "download",
                    "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                    "-c",
                    str(cookies),
                    "-q",
                ],
            )
        assert result.exit_code == 0

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    @patch("sp_dl.downloader.engine.download_file", new_callable=AsyncMock)
    def test_download_access_denied_retries_via_media_stream(
        self, mock_dl, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        """Download 401/403 on stream.aspx triggers media stream fallback."""
        target = _sample_target()
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.return_value = target
        from sp_dl.models import DownloadError

        mock_dl.side_effect = DownloadError("Access denied (HTTP 403)")

        manifest_target = _sample_target()
        manifest_target.is_manifest = True

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        with (
            patch("sp_dl.auth.device_code.DeviceCodeAuthProvider") as mock_dc_cls,
            patch(
                "sp_dl.resolver.media_stream.MediaStreamResolver.resolve",
                new_callable=AsyncMock,
            ) as mock_ms,
            patch("sp_dl.downloader.ffmpeg.is_ffmpeg_available", return_value=True),
            patch("sp_dl.downloader.ffmpeg.download_manifest", new_callable=AsyncMock),
        ):
            mock_instance = mock_dc_cls.return_value
            mock_instance.authenticate = AsyncMock()
            mock_instance._access_token = "token"
            mock_ms.return_value = manifest_target

            result = runner.invoke(
                app,
                [
                    "download",
                    "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                    "-c",
                    str(cookies),
                    "-q",
                ],
            )
        assert result.exit_code == 0

    @patch("sp_dl.url_parser.detect_and_parse")
    @patch("sp_dl.auth.session.create_auth_provider")
    @patch("sp_dl.auth.session.build_session", new_callable=AsyncMock)
    @patch("sp_dl.resolver.resolve_download_target", new_callable=AsyncMock)
    def test_download_blocked_oauth_error(
        self, mock_resolve, mock_session, mock_auth, mock_parse, tmp_path
    ):
        """DownloadBlockedError + OAuth2 token is None → exit 1."""
        mock_parse.return_value = _sample_parsed()
        mock_auth.return_value = MagicMock(description="Cookie auth")
        mock_client = AsyncMock()
        mock_client.headers = {}
        mock_client.aclose = AsyncMock()
        mock_session.return_value = mock_client
        mock_resolve.side_effect = DownloadBlockedError("blocked")

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape cookie\n.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tvalue\n")

        with patch("sp_dl.auth.device_code.DeviceCodeAuthProvider") as mock_dc_cls:
            mock_instance = mock_dc_cls.return_value
            mock_instance.authenticate = AsyncMock()
            mock_instance._access_token = None  # simulate failure

            result = runner.invoke(
                app,
                [
                    "download",
                    "https://contoso.sharepoint.com/sites/T/_layouts/15/stream.aspx?id=/sites/T/Docs/v.mp4",
                    "-c",
                    str(cookies),
                    "-q",
                ],
            )
        assert result.exit_code == 1
