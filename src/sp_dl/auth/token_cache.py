"""Encrypted token cache for OAuth tokens."""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".config" / "sp-dl"
TOKEN_FILE = "token.json"


class TokenCache:
    """Persist OAuth tokens to disk with restricted permissions."""

    def __init__(self, cache_dir: Path | None = None):
        self._cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self._token_path = self._cache_dir / TOKEN_FILE

    def save(self, token_data: dict) -> None:
        """Save token data to disk with 0600 permissions."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Write atomically
        tmp_path = self._token_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(token_data, indent=2))

        # Set restrictive permissions (owner read/write only)
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)

        # Rename into place (atomic on most filesystems)
        tmp_path.rename(self._token_path)
        logger.debug(f"Token saved to {self._token_path}")

    def load(self) -> dict | None:
        """Load cached token data from disk."""
        if not self._token_path.exists():
            return None

        try:
            data = json.loads(self._token_path.read_text())
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load token cache: {e}")
            return None

    def clear(self) -> None:
        """Remove cached tokens."""
        if self._token_path.exists():
            self._token_path.unlink()
            logger.info("Token cache cleared")

    @property
    def path(self) -> Path:
        return self._token_path

    @property
    def exists(self) -> bool:
        return self._token_path.exists()
