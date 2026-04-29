"""Microsoft Graph API resolver."""

from __future__ import annotations

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


class GraphAPIResolver(Resolver):
    """Resolve files using the Microsoft Graph API."""

    def can_handle(self, parsed: ParsedURL) -> bool:
        # Graph API needs an OAuth token (Authorization header)
        # Can handle most URL types
        return parsed.url_type in (
            URLType.DIRECT_PATH,
            URLType.ONEDRIVE_PERSONAL,
            URLType.DOC_ASPX,
            URLType.STREAM_ASPX,
        )

    async def resolve(self, parsed: ParsedURL, client: httpx.AsyncClient) -> DownloadTarget:
        """Resolve via Graph API using site-relative path or item GUID."""
        # Check if we have an Authorization header
        auth_header = client.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise ResolveError("Graph API requires OAuth token (no Authorization header)")

        if parsed.source_doc_guid:
            return await self._resolve_by_guid(parsed, client)
        elif parsed.server_relative_path:
            return await self._resolve_by_path(parsed, client)
        else:
            raise ResolveError("Graph resolver needs either a path or GUID")

    async def _resolve_by_path(
        self, parsed: ParsedURL, client: httpx.AsyncClient
    ) -> DownloadTarget:
        """Resolve using site-relative path via Graph."""
        # Build the Graph URL for the file
        # First, get the site ID
        site_url = f"{GRAPH_BASE}/sites/{parsed.tenant_domain}:{parsed.site_path or '/'}"
        response = await client.get(site_url)

        if response.status_code == 401:
            raise AccessDeniedError("OAuth token expired or invalid")
        if response.status_code == 403:
            raise AccessDeniedError("Access denied via Graph API")
        if response.status_code != 200:
            raise ResolveError(f"Failed to resolve site: {response.status_code}")

        site_data = response.json()
        site_id = site_data["id"]

        # Get the file relative to the site's drive
        # Strip site path prefix to get drive-relative path
        drive_path = parsed.server_relative_path or ""
        if parsed.site_path and drive_path.startswith(parsed.site_path):
            drive_path = drive_path[len(parsed.site_path) :]

        # Remove leading /Shared Documents/ or similar
        # Graph wants the path relative to the drive root
        item_url = f"{GRAPH_BASE}/sites/{site_id}/drive/root:{drive_path}"
        response = await client.get(item_url)

        if response.status_code == 404:
            raise ResolveError(f"File not found via Graph: {drive_path}")
        if response.status_code != 200:
            raise ResolveError(f"Graph API error: {response.status_code} - {response.text[:200]}")

        return self._parse_drive_item(response.json())

    async def _resolve_by_guid(
        self, parsed: ParsedURL, client: httpx.AsyncClient
    ) -> DownloadTarget:
        """Resolve using document GUID."""
        # Try to find the item by searching
        site_url = f"{GRAPH_BASE}/sites/{parsed.tenant_domain}:{parsed.site_path or '/'}"
        response = await client.get(site_url)

        if response.status_code != 200:
            raise ResolveError(f"Failed to resolve site: {response.status_code}")

        site_data = response.json()
        site_id = site_data["id"]

        # Search for the item by unique ID
        search_url = f"{GRAPH_BASE}/sites/{site_id}/drive/root/search(q='{parsed.source_doc_guid}')"
        response = await client.get(search_url)

        if response.status_code != 200:
            raise ResolveError(f"Search failed: {response.status_code}")

        results = response.json().get("value", [])
        if not results:
            raise ResolveError(f"No file found with GUID: {parsed.source_doc_guid}")

        return self._parse_drive_item(results[0])

    def _parse_drive_item(self, item: dict) -> DownloadTarget:
        """Parse a Graph driveItem response into a DownloadTarget."""
        name = item.get("name", "unknown")
        size = item.get("size", 0)

        # Content type from file facet
        file_facet = item.get("file", {})
        content_type = file_facet.get("mimeType", "application/octet-stream")

        # Modified date
        modified_at = None
        modified_str = item.get("lastModifiedDateTime")
        if modified_str:
            with contextlib.suppress(ValueError, AttributeError):
                modified_at = datetime.fromisoformat(modified_str.replace("Z", "+00:00"))

        # Created by
        created_by = None
        created_by_data = item.get("createdBy", {}).get("user", {})
        if created_by_data:
            created_by = created_by_data.get("displayName")

        # Video info
        video_info = None
        video_facet = item.get("video", {})
        if video_facet:
            video_info = VideoInfo(
                duration_ms=video_facet.get("duration"),
                width=video_facet.get("width"),
                height=video_facet.get("height"),
                bitrate=video_facet.get("bitrate"),
            )

        # Download URL — pre-authenticated
        download_url = item.get("@microsoft.graph.downloadUrl", "")
        if not download_url:
            # Fallback: use content endpoint
            item_id = item.get("id", "")
            parent_ref = item.get("parentReference", {})
            drive_id = parent_ref.get("driveId", "")
            if drive_id and item_id:
                download_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"
            else:
                raise ResolveError("No download URL available in Graph response")

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

        # Pre-auth URLs don't need Authorization header
        requires_auth = "@microsoft.graph.downloadUrl" not in item

        return DownloadTarget(
            metadata=metadata,
            download_url=download_url,
            requires_auth_headers=requires_auth,
        )
