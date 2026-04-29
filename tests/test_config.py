"""Tests for SpDlConfig, resolve_output_path, and _sanitize_filename."""

from __future__ import annotations

from pathlib import Path

import pytest

from sp_dl.config import SpDlConfig, _sanitize_filename, resolve_output_path


class TestSpDlConfig:
    def test_default_values(self):
        config = SpDlConfig()
        assert config.output_template == "%(filename)s"
        assert config.no_overwrites is False
        assert config.retries == 5
        assert config.retry_wait == 5
        assert config.quiet is False
        assert config.verbose is False
        assert config.tenant == "common"

    def test_load_from_toml(self, tmp_path: Path):
        toml_content = b"""
[defaults]
output_template = "%(title)s.%(ext)s"
limit_rate = "5M"
retries = 10
retry_wait = 3
no_overwrites = true
quiet = true
cookies_file = "/tmp/cookies.txt"
cookies_from_browser = "chrome"

[auth]
tenant = "contoso.onmicrosoft.com"
client_id = "my-client-id"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_bytes(toml_content)

        config = SpDlConfig.load(config_file)

        assert config.output_template == "%(title)s.%(ext)s"
        assert config.limit_rate == "5M"
        assert config.retries == 10
        assert config.retry_wait == 3
        assert config.no_overwrites is True
        assert config.quiet is True
        assert config.cookies_file == "/tmp/cookies.txt"
        assert config.cookies_from_browser == "chrome"
        assert config.tenant == "contoso.onmicrosoft.com"
        assert config.client_id == "my-client-id"

    def test_load_nonexistent_file_returns_defaults(self, tmp_path: Path):
        config = SpDlConfig.load(tmp_path / "nonexistent.toml")
        assert config.output_template == "%(filename)s"
        assert config.tenant == "common"

    def test_load_invalid_toml_returns_defaults(self, tmp_path: Path):
        bad_file = tmp_path / "bad.toml"
        bad_file.write_bytes(b"this is not valid toml {{{")

        config = SpDlConfig.load(bad_file)
        assert config.output_template == "%(filename)s"

    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SP_DL_COOKIES", "/env/cookies.txt")
        monkeypatch.setenv("SP_DL_TENANT", "env-tenant")
        monkeypatch.setenv("SP_DL_CLIENT_ID", "env-client")
        monkeypatch.setenv("SP_DL_OUTPUT", "%(title)s")

        config = SpDlConfig.load(tmp_path / "nonexistent.toml")
        assert config.cookies_file == "/env/cookies.txt"
        assert config.tenant == "env-tenant"
        assert config.client_id == "env-client"
        assert config.output_template == "%(title)s"

    def test_env_overrides_toml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        toml_content = b"""
[auth]
tenant = "toml-tenant"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_bytes(toml_content)

        monkeypatch.setenv("SP_DL_TENANT", "env-tenant")
        config = SpDlConfig.load(config_file)
        assert config.tenant == "env-tenant"

    def test_apply_toml_partial(self):
        config = SpDlConfig()
        config._apply_toml({"defaults": {"retries": 20}})
        assert config.retries == 20
        assert config.output_template == "%(filename)s"  # unchanged

    def test_apply_toml_empty(self):
        config = SpDlConfig()
        config._apply_toml({})
        assert config.retries == 5  # default


class TestResolveOutputPath:
    def test_basic_filename(self):
        result = resolve_output_path("%(filename)s", {"filename": "video.mp4"})
        assert result == Path("video.mp4")

    def test_template_with_multiple_fields(self):
        result = resolve_output_path(
            "%(site)s/%(folder)s/%(filename)s",
            {"site": "Team", "folder": "Recordings", "filename": "video.mp4"},
        )
        assert result == Path("Team/Recordings/video.mp4")

    def test_output_dir_prepended(self):
        result = resolve_output_path(
            "%(filename)s",
            {"filename": "video.mp4"},
            output_dir=Path("/tmp/downloads"),
        )
        assert result == Path("/tmp/downloads/video.mp4")

    def test_absolute_path_not_prepended(self):
        result = resolve_output_path(
            "/absolute/%(filename)s",
            {"filename": "video.mp4"},
            output_dir=Path("/tmp/other"),
        )
        assert result == Path("/absolute/video.mp4")

    def test_missing_field_kept(self):
        result = resolve_output_path("%(missing)s", {"filename": "video.mp4"})
        assert str(result) == "%(missing)s"

    def test_none_value_replaced_with_unknown(self):
        result = resolve_output_path("%(title)s.mp4", {"title": None})
        assert result == Path("unknown.mp4")

    def test_sanitizes_values(self):
        result = resolve_output_path("%(filename)s", {"filename": 'file<>:"/\\|?*.mp4'})
        assert "<" not in str(result)
        assert ">" not in str(result)


class TestSanitizeFilename:
    def test_removes_invalid_chars(self):
        assert _sanitize_filename('test<>:"/\\|?*.mp4') == "test_________.mp4"

    def test_removes_control_chars(self):
        assert _sanitize_filename("test\x00file.mp4") == "testfile.mp4"

    def test_strips_dots_and_spaces(self):
        assert _sanitize_filename("  file.mp4  ") == "file.mp4"
        assert _sanitize_filename("...") == "unnamed"

    def test_empty_string(self):
        assert _sanitize_filename("") == "unnamed"

    def test_only_spaces(self):
        assert _sanitize_filename("   ") == "unnamed"

    def test_normal_filename_unchanged(self):
        assert _sanitize_filename("video.mp4") == "video.mp4"
