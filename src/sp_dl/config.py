"""Configuration management for sp-dl."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # type: ignore[assignment]

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "sp-dl"
CONFIG_FILE = "config.toml"


@dataclass
class SpDlConfig:
    """Application configuration."""

    # Output
    output_template: str = "%(filename)s"
    no_overwrites: bool = False

    # Auth
    cookies_file: str = ""
    cookies_from_browser: str = ""
    tenant: str = "common"
    client_id: str = ""

    # Download
    limit_rate: str = ""
    retries: int = 5
    retry_wait: int = 5

    # Display
    quiet: bool = False
    verbose: bool = False

    @classmethod
    def load(cls, config_path: Path | None = None) -> SpDlConfig:
        """Load config from file, environment variables, with defaults."""
        config = cls()

        # Load from file
        path = config_path or (DEFAULT_CONFIG_DIR / CONFIG_FILE)
        if path.exists() and tomllib is not None:
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
                config._apply_toml(data)
            except Exception as e:
                logger.warning(f"Failed to load config from {path}: {e}")

        # Override with environment variables
        config._apply_env()

        return config

    def _apply_toml(self, data: dict) -> None:
        """Apply parsed TOML data to config."""
        defaults = data.get("defaults", {})
        auth = data.get("auth", {})

        if "output_template" in defaults:
            self.output_template = defaults["output_template"]
        if "cookies_file" in defaults:
            self.cookies_file = defaults["cookies_file"]
        if "cookies_from_browser" in defaults:
            self.cookies_from_browser = defaults["cookies_from_browser"]
        if "limit_rate" in defaults:
            self.limit_rate = defaults["limit_rate"]
        if "retries" in defaults:
            self.retries = int(defaults["retries"])
        if "retry_wait" in defaults:
            self.retry_wait = int(defaults["retry_wait"])
        if "no_overwrites" in defaults:
            self.no_overwrites = bool(defaults["no_overwrites"])
        if "quiet" in defaults:
            self.quiet = bool(defaults["quiet"])

        if "tenant" in auth:
            self.tenant = auth["tenant"]
        if "client_id" in auth:
            self.client_id = auth["client_id"]

    def _apply_env(self) -> None:
        """Override config with environment variables."""
        env_map = {
            "SP_DL_COOKIES": "cookies_file",
            "SP_DL_TENANT": "tenant",
            "SP_DL_CLIENT_ID": "client_id",
            "SP_DL_OUTPUT": "output_template",
        }

        for env_var, attr in env_map.items():
            value = os.environ.get(env_var)
            if value:
                setattr(self, attr, value)


def resolve_output_path(
    template: str,
    metadata: dict,
    output_dir: Path | None = None,
) -> Path:
    """
    Resolve output template to a file path.

    Supported fields: %(filename)s, %(title)s, %(ext)s, %(site)s,
    %(folder)s, %(date)s, %(author)s, %(id)s
    """
    # Apply template substitution
    result = template
    for key, value in metadata.items():
        placeholder = f"%({key})s"
        if placeholder in result:
            # Sanitize value for filesystem
            safe_value = _sanitize_filename(str(value)) if value else "unknown"
            result = result.replace(placeholder, safe_value)

    path = Path(result)

    # Prepend output directory if specified
    if output_dir and not path.is_absolute():
        path = output_dir / path

    return path


def _sanitize_filename(name: str) -> str:
    """Remove or replace characters that are invalid in filenames."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    # Remove control characters
    name = "".join(c for c in name if ord(c) >= 32)
    # Trim whitespace and dots
    name = name.strip(". ")
    return name or "unnamed"
