"""Tests for CLI commands."""

from __future__ import annotations

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
