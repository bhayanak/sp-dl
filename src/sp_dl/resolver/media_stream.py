"""Media streaming resolver for download-blocked SharePoint videos.

When SharePoint admins block direct downloads (`isDownloadBlocked: True`),
videos can still be accessed via the media proxy streaming endpoint with
an OAuth2 Bearer token. This resolver:

1. Extracts video metadata from stream.aspx g_fileInfo or REST API
2. Acquires an OAuth2 token via device code flow
3. Builds a DASH manifest URL via the media proxy
4. Returns a manifest DownloadTarget (handled by ffmpeg)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

from sp_dl.constants import (
    MEDIA_PROXY_MANIFEST_URL,
    SP_V2_DRIVE,
    SP_V2_DRIVE_ITEM_BY_PATH,
)
from sp_dl.models import (
    DownloadTarget,
    FileMetadata,
    ParsedURL,
    ResolveError,
    URLType,
    VideoInfo,
)
from sp_dl.resolver.base import Resolver

logger = logging.getLogger(__name__)


class MediaStreamResolver(Resolver):
    """Resolve download-blocked videos via the media proxy DASH endpoint."""

    def __init__(self, oauth_token: str | None = None):
        self._oauth_token = oauth_token

    def can_handle(self, parsed: ParsedURL) -> bool:
        return parsed.url_type == URLType.STREAM_ASPX

    async def resolve(self, parsed: ParsedURL, client: httpx.AsyncClient) -> DownloadTarget:
        """Resolve stream.aspx video via media proxy.

        Requires:
        - Cookies in the client (to load stream.aspx and get g_fileInfo)
          OR working REST API access for drive/item ID lookup
        - OAuth2 token (set via set_oauth_token or passed at init)
        """
        if not self._oauth_token:
            raise ResolveError(
                "OAuth2 token required for download-blocked videos. "
                "Run: sp-dl auth login --tenant YOUR_TENANT"
            )

        # Step 1: Get drive/item IDs (try g_fileInfo first, then REST API)
        page_info = await self._extract_page_info(parsed, client)
        if not page_info:
            # Fallback: use v2.0 REST API to get drive/item IDs
            logger.info("g_fileInfo unavailable, falling back to REST API for drive/item IDs")
            page_info = await self._extract_from_rest_api(parsed, client)

        if not page_info:
            raise ResolveError(
                "Could not extract video metadata from stream.aspx page or REST API. "
                "Ensure your cookies are valid (export fresh cookies from browser)."
            )

        # Step 2: Build the DASH manifest URL
        drive_id = page_info["drive_id"]
        item_id = page_info["item_id"]
        transform_host = page_info.get("transform_host", "southcentralus1-mediap.svc.ms")
        farmid = page_info.get("farmid", "191780")

        docid = quote(
            f"https://{parsed.tenant_domain}:443/_api/v2.1/drives/{drive_id}/items/{item_id}",
            safe="",
        )

        manifest_url = MEDIA_PROXY_MANIFEST_URL.format(
            transform_host=transform_host,
            farmid=farmid,
            docid=docid,
            access_token=self._oauth_token,
        )

        # Step 3: Build metadata
        name = page_info.get("name", "video.mp4")
        size = page_info.get("size", 0)
        duration_ms = page_info.get("duration_ms")
        video_info = VideoInfo(duration_ms=duration_ms) if duration_ms else None

        metadata = FileMetadata(
            name=name,
            size_bytes=size,
            content_type="video/mp4",
            server_relative_path=parsed.server_relative_path,
            video_info=video_info,
        )

        return DownloadTarget(
            metadata=metadata,
            download_url=manifest_url,
            requires_auth_headers=False,  # Token is in URL
            is_manifest=True,  # ffmpeg will handle the DASH download
        )

    def set_oauth_token(self, token: str) -> None:
        """Set the OAuth2 token for media proxy access."""
        self._oauth_token = token

    async def _extract_page_info(self, parsed: ParsedURL, client: httpx.AsyncClient) -> dict | None:
        """Extract g_fileInfo from stream.aspx HTML.

        Tries cookies first, then OAuth2 Bearer token.
        """
        headers_list = [
            {"Accept": "text/html"},  # Uses client's cookies
        ]
        if self._oauth_token:
            headers_list.append(
                {
                    "Accept": "text/html",
                    "Authorization": f"Bearer {self._oauth_token}",
                }
            )

        for headers in headers_list:
            try:
                response = await client.get(parsed.original_url, headers=headers)
                if response.status_code != 200:
                    logger.debug(f"stream.aspx returned {response.status_code}")
                    continue

                result = self._parse_file_info(response.text)
                if result:
                    return result
            except httpx.HTTPError as e:
                logger.debug(f"Failed to fetch stream.aspx: {e}")
                continue

        return None

    async def _extract_from_rest_api(
        self, parsed: ParsedURL, client: httpx.AsyncClient
    ) -> dict | None:
        """Get drive/item IDs from the SharePoint v2.0 REST API.

        Uses the OAuth2 token (Bearer auth) instead of cookies,
        since cookies may be expired when we reach this fallback.
        """
        site_path = parsed.site_path or ""
        tenant_domain = parsed.tenant_domain
        server_path = parsed.server_relative_path
        if not server_path:
            return None

        # Use OAuth2 token for auth since cookies may be expired
        auth_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._oauth_token}",
        }

        try:
            # Step 1: Get drive root path
            drive_url = SP_V2_DRIVE.format(tenant_domain=tenant_domain, site_path=site_path)
            resp = await client.get(drive_url, headers=auth_headers)
            if resp.status_code != 200:
                logger.debug(f"v2.0 drive request failed: {resp.status_code}")
                return None

            drive_data = resp.json()
            drive_web_url = drive_data.get("webUrl", "")
            drive_root_path = urlparse(drive_web_url).path.rstrip("/")
            if not drive_root_path:
                return None

            # Step 2: Compute drive-relative path
            if not server_path.startswith(drive_root_path):
                logger.debug(f"File path {server_path} not under drive root {drive_root_path}")
                return None

            drive_relative = server_path[len(drive_root_path) :].lstrip("/")
            if not drive_relative:
                return None

            # Step 3: Get item info (contains driveId and item id)
            item_url = SP_V2_DRIVE_ITEM_BY_PATH.format(
                tenant_domain=tenant_domain,
                site_path=site_path,
                drive_relative_path=quote(drive_relative, safe="/"),
            )
            resp = await client.get(item_url, headers=auth_headers)
            if resp.status_code != 200:
                logger.debug(f"v2.0 item request failed: {resp.status_code}")
                return None

            item = resp.json()
            drive_id = item.get("parentReference", {}).get("driveId")
            item_id = item.get("id")

            if not drive_id or not item_id:
                logger.debug("v2.0 response missing driveId or item id")
                return None

            name = item.get("name", Path(server_path).name)
            size = item.get("size", 0)

            logger.info(f"Got drive/item IDs from REST API: drive={drive_id}, item={item_id}")
            return {
                "name": name,
                "size": size,
                "drive_id": drive_id,
                "item_id": item_id,
                "transform_host": "southcentralus1-mediap.svc.ms",
                "farmid": "191780",
                "is_download_blocked": True,
                "duration_ms": None,
            }
        except httpx.HTTPError as e:
            logger.debug(f"REST API fallback failed: {e}")
            return None

    def _parse_file_info(self, html: str) -> dict | None:
        """Parse g_fileInfo JavaScript object from HTML."""
        match = re.search(r"var\s+g_fileInfo\s*=\s*(\{.+?\})\s*;", html, re.DOTALL)
        if not match:
            return None

        try:
            info = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        # Extract drive_id and item_id from .spItemUrl
        sp_item_url = info.get(".spItemUrl", "")
        drive_id = None
        item_id = info.get("VroomItemId")

        # Parse drive ID from .spItemUrl
        # e.g. "https://.../_api/v2.0/drives/{drive_id}/items/{item_id}"
        drive_match = re.search(r"/drives/([^/]+)", sp_item_url)
        if drive_match:
            drive_id = drive_match.group(1)

        if not drive_id or not item_id:
            logger.debug("Could not extract drive_id or item_id from g_fileInfo")
            return None

        # Extract transform host from .transformUrl
        transform_url = info.get(".transformUrl", "")
        transform_host = "southcentralus1-mediap.svc.ms"
        farmid = "191780"

        if transform_url:
            host_match = re.match(r"https?://([^/]+)", transform_url)
            if host_match:
                transform_host = host_match.group(1)
            farmid_match = re.search(r"farmid=(\d+)", transform_url)
            if farmid_match:
                farmid = farmid_match.group(1)

        # Extract duration from MediaServiceFastMetadata
        duration_ms = None
        fast_meta = info.get("MediaServiceFastMetadata", "")
        if fast_meta and isinstance(fast_meta, str):
            try:
                meta_data = json.loads(fast_meta)
                duration_ms = meta_data.get("media", {}).get("duration")
            except json.JSONDecodeError:
                pass

        return {
            "name": info.get("name", "video.mp4"),
            "size": info.get("size", 0),
            "drive_id": drive_id,
            "item_id": item_id,
            "transform_host": transform_host,
            "farmid": farmid,
            "is_download_blocked": info.get("isDownloadBlocked", False),
            "duration_ms": duration_ms,
            "ctag": info.get(".ctag", ""),
        }
