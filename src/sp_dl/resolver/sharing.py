"""Sharing link resolver via Microsoft Graph /shares/ endpoint."""

from __future__ import annotations

import base64
import contextlib
import logging
from datetime import datetime

import httpx

from sp_dl.constants import GRAPH_BASE
from sp_dl.models import (
    AccessDeniedError,
    DownloadTarget,
    FileMetadata,
    ParsedURL,
    ResolveError,
    URLType,
    VideoInfo,
)
from sp_dl.resolver.base import Resolver

logger = logging.getLogger(__name__)


def encode_sharing_url(url: str) -> str:
    """
    Encode a sharing URL for the Graph /shares/ endpoint.

    Format: u!{base64url_encoded_sharing_url}
    See: https://learn.microsoft.com/en-us/graph/api/shares-get
    """
    encoded = base64.urlsafe_b64encode(url.encode()).decode()
    encoded = encoded.rstrip("=")
    return f"u!{encoded}"


class SharingLinkResolver(Resolver):
    """Resolve sharing links via the Graph /shares/ API."""

    def can_handle(self, parsed: ParsedURL) -> bool:
        return parsed.url_type == URLType.SHARING_LINK

    async def resolve(self, parsed: ParsedURL, client: httpx.AsyncClient) -> DownloadTarget:
        """Resolve a sharing link to a downloadable file."""
        # Encode the original URL for the shares API
        encoded = encode_sharing_url(parsed.original_url)

        # Request driveItem via shares endpoint
        shares_url = f"{GRAPH_BASE}/shares/{encoded}/driveItem"
        logger.debug(f"Resolving sharing link via: {shares_url}")

        response = await client.get(shares_url)

        if response.status_code == 401:
            raise AccessDeniedError("Authentication required for sharing link resolution")
        if response.status_code == 403:
            raise AccessDeniedError(
                "Access denied. The sharing link may have expired or "
                "your account doesn't have access."
            )
        if response.status_code == 404:
            raise ResolveError("Sharing link not found or has been revoked")
        if response.status_code != 200:
            raise ResolveError(
                f"Failed to resolve sharing link: {response.status_code} - {response.text[:200]}"
            )

        item = response.json()
        return self._parse_drive_item(item)

    def _parse_drive_item(self, item: dict) -> DownloadTarget:
        """Parse a Graph driveItem response into a DownloadTarget."""
        name = item.get("name", "unknown")
        size = item.get("size", 0)

        file_facet = item.get("file", {})
        content_type = file_facet.get("mimeType", "application/octet-stream")

        modified_at = None
        modified_str = item.get("lastModifiedDateTime")
        if modified_str:
            with contextlib.suppress(ValueError, AttributeError):
                modified_at = datetime.fromisoformat(modified_str.replace("Z", "+00:00"))

        created_by = None
        created_by_data = item.get("createdBy", {}).get("user", {})
        if created_by_data:
            created_by = created_by_data.get("displayName")

        video_info = None
        video_facet = item.get("video", {})
        if video_facet:
            video_info = VideoInfo(
                duration_ms=video_facet.get("duration"),
                width=video_facet.get("width"),
                height=video_facet.get("height"),
                bitrate=video_facet.get("bitrate"),
            )

        # Pre-authenticated download URL
        download_url = item.get("@microsoft.graph.downloadUrl", "")
        requires_auth = True

        if not download_url:
            # Fallback to content endpoint
            item_id = item.get("id", "")
            parent_ref = item.get("parentReference", {})
            drive_id = parent_ref.get("driveId", "")
            if drive_id and item_id:
                download_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"
            else:
                raise ResolveError("No download URL in sharing link response")
        else:
            requires_auth = False  # Pre-auth URL

        metadata = FileMetadata(
            name=name,
            size_bytes=size,
            content_type=content_type,
            modified_at=modified_at,
            created_by=created_by,
            download_url=download_url,
            drive_item_id=item.get("id"),
            video_info=video_info,
        )

        return DownloadTarget(
            metadata=metadata,
            download_url=download_url,
            requires_auth_headers=requires_auth,
        )
