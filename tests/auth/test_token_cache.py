"""Tests for token cache."""

from __future__ import annotations

from pathlib import Path

from sp_dl.auth.token_cache import TokenCache


class TestTokenCache:
    def test_save_and_load(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        data = {"access_token": "tok123", "refresh_token": "ref456", "expires_at": 9999999}
        cache.save(data)

        loaded = cache.load()
        assert loaded is not None
        assert loaded["access_token"] == "tok123"
        assert loaded["refresh_token"] == "ref456"

    def test_load_nonexistent(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        assert cache.load() is None

    def test_clear(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save({"token": "value"})
        assert cache.exists is True
        cache.clear()
        assert cache.exists is False
        assert cache.load() is None

    def test_clear_nonexistent(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.clear()  # Should not raise

    def test_path_property(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        assert cache.path == tmp_path / "token.json"

    def test_exists_property(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        assert cache.exists is False
        cache.save({"x": 1})
        assert cache.exists is True

    def test_file_permissions(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save({"secret": "data"})
        mode = cache.path.stat().st_mode & 0o777
        assert mode == 0o600  # owner read/write only

    def test_creates_directory(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path / "sub" / "dir")
        cache.save({"x": 1})
        assert cache.path.exists()
        assert cache.path.parent.is_dir()

    def test_load_invalid_json(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        # Write invalid JSON directly
        cache._cache_dir.mkdir(parents=True, exist_ok=True)
        cache._token_path.write_text("not json {{{")
        assert cache.load() is None

    def test_atomic_write(self, tmp_path: Path):
        cache = TokenCache(cache_dir=tmp_path)
        cache.save({"first": "write"})
        cache.save({"second": "write"})
        loaded = cache.load()
        assert loaded["second"] == "write"
