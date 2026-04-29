"""Tests for CLI commands."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from sp_dl.cli import app

runner = CliRunner()


class TestCLI:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "sp-dl" in result.output

    def test_no_args_shows_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "download" in result.output.lower()

    def test_help_shows_quick_start(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Quick start" in result.output or "cookies" in result.output.lower()

    def test_download_help(self):
        result = runner.invoke(app, ["download", "--help"])
        assert result.exit_code == 0
        assert "cookies" in result.output.lower()
        assert "Authentication" in result.output or "auth" in result.output.lower()

    def test_auth_help(self):
        result = runner.invoke(app, ["auth", "--help"])
        assert result.exit_code == 0
        assert "login" in result.output.lower()

    def test_quickstart(self):
        result = runner.invoke(app, ["quickstart"])
        assert result.exit_code == 0
        assert "Quick Start" in result.output
        assert "cookies" in result.output.lower()

    def test_batch_help(self):
        result = runner.invoke(app, ["batch", "--help"])
        assert result.exit_code == 0
        assert "URLs" in result.output or "urls" in result.output.lower()

    def test_auth_status_no_cache(self, tmp_path: Path):
        with patch("sp_dl.auth.token_cache.TokenCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.exists = False
            result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Not logged in" in result.output

    def test_auth_status_with_valid_token(self, tmp_path: Path):
        with patch("sp_dl.auth.token_cache.TokenCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.exists = True
            mock_cache.load.return_value = {
                "access_token": "tok",
                "refresh_token": "ref",
                "expires_at": time.time() + 3600,
            }
            mock_cache.path = tmp_path / "token.json"
            result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Yes" in result.output

    def test_auth_status_with_expired_token(self, tmp_path: Path):
        with patch("sp_dl.auth.token_cache.TokenCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.exists = True
            mock_cache.load.return_value = {
                "access_token": "tok",
                "expires_at": time.time() - 100,
            }
            mock_cache.path = tmp_path / "token.json"
            result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Expired" in result.output

    def test_auth_logout_with_cache(self):
        with patch("sp_dl.auth.token_cache.TokenCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.exists = True
            result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output

    def test_auth_logout_no_cache(self):
        with patch("sp_dl.auth.token_cache.TokenCache") as mock_cache_cls:
            mock_cache = mock_cache_cls.return_value
            mock_cache.exists = False
            result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        assert "No cached tokens" in result.output

    def test_batch_missing_file(self, tmp_path: Path):
        result = runner.invoke(app, ["batch", str(tmp_path / "missing.txt")])
        assert result.exit_code == 1

    def test_batch_empty_file(self, tmp_path: Path):
        f = tmp_path / "urls.txt"
        f.write_text("# just a comment\n\n")
        result = runner.invoke(app, ["batch", str(f)])
        assert result.exit_code == 0
        assert "No URLs" in result.output

    def test_download_invalid_url(self):
        result = runner.invoke(
            app,
            ["download", "https://not-sharepoint.com/file.mp4", "-c", "/tmp/nonexistent.txt"],
        )
        assert result.exit_code == 1


class TestNormalizeTenant:
    def test_short_name(self):
        from sp_dl.cli import _normalize_tenant

        assert _normalize_tenant("contoso") == "contoso.onmicrosoft.com"

    def test_full_onmicrosoft(self):
        from sp_dl.cli import _normalize_tenant

        assert _normalize_tenant("contoso.onmicrosoft.com") == "contoso.onmicrosoft.com"

    def test_sharepoint_url(self):
        from sp_dl.cli import _normalize_tenant

        assert _normalize_tenant("https://contoso.sharepoint.com") == "contoso.onmicrosoft.com"

    def test_sharepoint_my_url(self):
        from sp_dl.cli import _normalize_tenant

        result = _normalize_tenant("https://contoso-my.sharepoint.com/personal/user")
        assert result == "contoso.onmicrosoft.com"

    def test_sharepoint_domain(self):
        from sp_dl.cli import _normalize_tenant

        assert _normalize_tenant("contoso.sharepoint.com") == "contoso.onmicrosoft.com"

    def test_fqdn_passthrough(self):
        from sp_dl.cli import _normalize_tenant

        assert _normalize_tenant("custom.domain.com") == "custom.domain.com"


class TestSetupLogging:
    def _reset_logging(self):
        """Reset the root logger so basicConfig works again."""
        import logging

        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.WARNING)

    def test_debug_logging(self):
        import logging

        from sp_dl.cli import _setup_logging

        self._reset_logging()
        _setup_logging(verbose=False, debug=True, quiet=False)
        assert logging.getLogger().level == logging.DEBUG

    def test_verbose_logging(self):
        import logging

        from sp_dl.cli import _setup_logging

        self._reset_logging()
        _setup_logging(verbose=True, debug=False, quiet=False)
        assert logging.getLogger().level == logging.INFO

    def test_quiet_logging(self):
        import logging

        from sp_dl.cli import _setup_logging

        self._reset_logging()
        _setup_logging(verbose=False, debug=False, quiet=True)
        assert logging.getLogger().level == logging.ERROR

    def test_default_logging(self):
        import logging

        from sp_dl.cli import _setup_logging

        self._reset_logging()
        _setup_logging(verbose=False, debug=False, quiet=False)
        assert logging.getLogger().level == logging.WARNING
