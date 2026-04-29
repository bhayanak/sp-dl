"""Core data models for sharepoint-dl."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class URLType(Enum):
    """SharePoint URL pattern types."""

    STREAM_ASPX = "stream_aspx"
    SHARING_LINK = "sharing_link"
    DIRECT_PATH = "direct_path"
    DOC_ASPX = "doc_aspx"
    ONEDRIVE_PERSONAL = "onedrive"


class AuthMethod(Enum):
    """Supported authentication methods."""

    COOKIES = "cookies"
    DEVICE_CODE = "device_code"
    INTERACTIVE = "interactive"
    CLIENT_CREDENTIALS = "client_credentials"


class DownloadStatus(Enum):
    """Status of a download operation."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ParsedURL:
    """Result of parsing a SharePoint URL."""

    original_url: str
    url_type: URLType
    tenant: str  # "contoso" from contoso.sharepoint.com
    tenant_domain: str  # "contoso.sharepoint.com"
    site_path: str | None = None  # "/sites/Team"
    server_relative_path: str | None = None  # "/sites/Team/Shared Documents/vid.mp4"
    sharing_token: str | None = None  # encoded sharing ID
    source_doc_guid: str | None = None  # GUID from Doc.aspx
    is_personal: bool = False  # OneDrive (tenant-my) vs SharePoint site


@dataclass
class VideoInfo:
    """Video-specific metadata."""

    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    audio_format: str | None = None
    video_codec: str | None = None


@dataclass
class FileMetadata:
    """Metadata about a file to be downloaded."""

    name: str
    size_bytes: int
    content_type: str  # "video/mp4"
    etag: str | None = None
    modified_at: datetime | None = None
    created_by: str | None = None
    download_url: str | None = None  # pre-authenticated download URL
    server_relative_path: str | None = None
    drive_item_id: str | None = None
    video_info: VideoInfo | None = None


@dataclass
class DownloadTarget:
    """Resolved download target with all info needed to download."""

    metadata: FileMetadata
    download_url: str  # final URL to download from
    output_path: Path = field(default_factory=lambda: Path("."))
    requires_auth_headers: bool = True  # pre-auth URLs don't need headers
    is_manifest: bool = False  # True if DASH/HLS (needs ffmpeg)
    status: DownloadStatus = DownloadStatus.PENDING


@dataclass
class DownloadResult:
    """Result of a download operation."""

    target: DownloadTarget
    output_path: Path
    bytes_downloaded: int
    elapsed_seconds: float
    resumed: bool = False


class SpDlError(Exception):
    """Base exception for sharepoint-dl."""


class AuthError(SpDlError):
    """Authentication failed."""


class AccessDeniedError(SpDlError):
    """Access denied (HTTP 403)."""


class DownloadBlockedError(SpDlError):
    """Download blocked by SharePoint admin policy (isDownloadBlocked)."""


class FileNotFoundOnServerError(SpDlError):
    """File not found (HTTP 404)."""


class ThrottleError(SpDlError):
    """SharePoint throttle limit exceeded."""


class DownloadError(SpDlError):
    """Download failed."""


class URLParseError(SpDlError):
    """Failed to parse SharePoint URL."""


class ResolveError(SpDlError):
    """Failed to resolve URL to download target."""
