"""SharePoint REST API resolver."""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from sp_dl.constants import (
    SP_DOWNLOAD_ASPX,
    SP_DOWNLOAD_BY_PATH,
    SP_REST_FILE_BY_PATH,
    SP_REST_FILE_CONTENT,
    SP_V2_DRIVE,
    SP_V2_DRIVE_ITEM_BY_PATH,
    VIDEO_EXTENSIONS,
)
from sp_dl.models import (
    AccessDeniedError,
    DownloadTarget,
    FileMetadata,
    FileNotFoundOnServerError,
    ParsedURL,
    ResolveError,
)
from sp_dl.resolver.base import Resolver

logger = logging.getLogger(__name__)


class SharePointRESTResolver(Resolver):
    """Resolve files using the SharePoint REST API."""

    def can_handle(self, parsed: ParsedURL) -> bool:
        # Can handle anything with a server-relative path
        return parsed.server_relative_path is not None

    async def resolve(self, parsed: ParsedURL, client: httpx.AsyncClient) -> DownloadTarget:
        """Resolve file metadata and download URL via SP REST API.

        Strategy order:
        1. v1 REST API → get metadata + UniqueId → download.aspx?UniqueId=
        2. v2.0 drive API → get @content.downloadUrl (pre-authenticated)
        3. download.aspx?SourceUrl= as last resort
        """
        if not parsed.server_relative_path:
            raise ResolveError("No server-relative path available for REST resolution")

        # Try v1 REST API first
        try:
            return await self._resolve_v1(parsed, client)
        except (ResolveError, httpx.HTTPError) as v1_err:
            logger.debug(f"v1 REST API failed: {v1_err}")

        # Try v2.0 drive API (returns pre-authenticated download URL)
        try:
            result = await self._resolve_v2(parsed, client)
            if result:
                return result
        except (httpx.HTTPError, Exception) as v2_err:
            logger.debug(f"v2.0 API failed: {v2_err}")

        # Last resort: download.aspx?SourceUrl=
        return self._resolve_source_url_fallback(parsed)

    async def _resolve_v1(self, parsed: ParsedURL, client: httpx.AsyncClient) -> DownloadTarget:
        """Resolve via SharePoint REST v1 API (OData)."""
        site_path = parsed.site_path or ""
        tenant_domain = parsed.tenant_domain

        # URL-encode the path for OData: encode spaces/special chars, keep slashes
        encoded_path = quote(parsed.server_relative_path, safe="/").replace("'", "''")

        metadata_url = SP_REST_FILE_BY_PATH.format(
            tenant_domain=tenant_domain,
            site_path=site_path,
            server_relative_path=encoded_path,
        )

        logger.debug(f"SP REST v1 request: {metadata_url}")

        response = await client.get(
            metadata_url,
            headers={"Accept": "application/json;odata=verbose"},
        )

        if response.status_code == 401:
            raise AccessDeniedError(
                "Authentication expired or invalid. Re-export cookies or run: sp-dl auth login"
            )
        if response.status_code == 403:
            raise AccessDeniedError(
                "Access denied. You may not have permission to download this file."
            )
        if response.status_code == 404:
            raise FileNotFoundOnServerError(f"File not found: {parsed.server_relative_path}")
        if response.status_code != 200:
            raise ResolveError(f"SP REST API error ({response.status_code}): {response.text[:200]}")

        data = response.json()
        result = data.get("d", data)

        name = result.get("Name", Path(parsed.server_relative_path).name)
        size_bytes = int(result.get("Length", 0))
        content_type = result.get("ContentType", "application/octet-stream")
        etag = result.get("ETag")
        unique_id = result.get("UniqueId")
        time_modified = result.get("TimeLastModified")
        modified_at = None
        if time_modified:
            with contextlib.suppress(ValueError, AttributeError):
                modified_at = datetime.fromisoformat(time_modified.replace("Z", "+00:00"))

        # Determine download URL strategy
        file_ext = Path(name).suffix.lower()
        is_video = file_ext in VIDEO_EXTENSIONS or "video/" in content_type

        if is_video and unique_id:
            download_url = SP_DOWNLOAD_ASPX.format(
                tenant_domain=tenant_domain,
                site_path=site_path,
                unique_id=unique_id,
            )
            logger.debug(f"Using download.aspx (UniqueId) for video: {download_url}")
        elif is_video:
            download_url = SP_DOWNLOAD_BY_PATH.format(
                tenant_domain=tenant_domain,
                site_path=site_path,
                server_relative_path=quote(parsed.server_relative_path, safe="/"),
            )
            logger.debug(f"Using download.aspx (SourceUrl) for video: {download_url}")
        else:
            download_url = SP_REST_FILE_CONTENT.format(
                tenant_domain=tenant_domain,
                site_path=site_path,
                server_relative_path=encoded_path,
            )

        metadata = FileMetadata(
            name=name,
            size_bytes=size_bytes,
            content_type=content_type,
            etag=etag,
            modified_at=modified_at,
            server_relative_path=parsed.server_relative_path,
        )

        return DownloadTarget(
            metadata=metadata,
            download_url=download_url,
            requires_auth_headers=True,
        )

    async def _resolve_v2(
        self, parsed: ParsedURL, client: httpx.AsyncClient
    ) -> DownloadTarget | None:
        """Resolve via SharePoint v2.0 drive API (modern OneDrive-style).

        Returns a pre-authenticated @content.downloadUrl that works without cookies.
        """
        site_path = parsed.site_path or ""
        tenant_domain = parsed.tenant_domain

        # Step 1: Get drive info to find the drive root path
        drive_url = SP_V2_DRIVE.format(tenant_domain=tenant_domain, site_path=site_path)
        logger.debug(f"SP v2.0 drive request: {drive_url}")

        resp = await client.get(drive_url, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            logger.debug(f"v2.0 drive request failed: {resp.status_code}")
            return None

        drive_data = resp.json()
        drive_web_url = drive_data.get("webUrl", "")

        # Extract drive root server-relative path from webUrl
        # e.g., "https://hpe-my.sharepoint.com/personal/user/Documents" → "/personal/user/Documents"
        drive_root_path = urlparse(drive_web_url).path.rstrip("/")
        if not drive_root_path:
            logger.debug("Could not determine drive root path")
            return None

        # Step 2: Get drive-relative path by stripping the drive root prefix
        server_path = parsed.server_relative_path
        if not server_path.startswith(drive_root_path):
            logger.debug(f"File path {server_path} not under drive root {drive_root_path}")
            return None

        drive_relative = server_path[len(drive_root_path) :].lstrip("/")
        if not drive_relative:
            return None

        # Step 3: Get item by drive-relative path
        item_url = SP_V2_DRIVE_ITEM_BY_PATH.format(
            tenant_domain=tenant_domain,
            site_path=site_path,
            drive_relative_path=quote(drive_relative, safe="/"),
        )
        logger.debug(f"SP v2.0 item request: {item_url}")

        resp = await client.get(item_url, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            logger.debug(f"v2.0 item request failed: {resp.status_code}")
            return None

        item = resp.json()

        # The key: @content.downloadUrl is a pre-authenticated Azure blob URL
        download_url = item.get("@content.downloadUrl") or item.get("@microsoft.graph.downloadUrl")
        if not download_url:
            logger.debug("v2.0 response has no downloadUrl")
            return None

        name = item.get("name", Path(parsed.server_relative_path).name)
        size = item.get("size", 0)
        mime = "application/octet-stream"
        if "file" in item and "mimeType" in item["file"]:
            mime = item["file"]["mimeType"]

        logger.info(f"Resolved via v2.0 API with pre-authenticated URL ({size} bytes)")

        return DownloadTarget(
            metadata=FileMetadata(
                name=name,
                size_bytes=size,
                content_type=mime,
                server_relative_path=parsed.server_relative_path,
            ),
            download_url=download_url,
            requires_auth_headers=False,  # Pre-authenticated URL
        )

    def _resolve_source_url_fallback(self, parsed: ParsedURL) -> DownloadTarget:
        """Last resort: download.aspx?SourceUrl= (may not work for all sites)."""
        site_path = parsed.site_path or ""
        download_url = SP_DOWNLOAD_BY_PATH.format(
            tenant_domain=parsed.tenant_domain,
            site_path=site_path,
            server_relative_path=quote(parsed.server_relative_path, safe="/"),
        )
        logger.info(f"Using download.aspx SourceUrl fallback: {download_url}")

        name = Path(parsed.server_relative_path).name
        return DownloadTarget(
            metadata=FileMetadata(
                name=name,
                size_bytes=0,
                content_type="application/octet-stream",
                server_relative_path=parsed.server_relative_path,
            ),
            download_url=download_url,
            requires_auth_headers=True,
        )
