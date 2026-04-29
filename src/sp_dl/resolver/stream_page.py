"""Stream.aspx page parser — extract video URLs from embedded player."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from sp_dl.constants import SP_DOWNLOAD_BY_PATH
from sp_dl.models import (
    DownloadBlockedError,
    DownloadTarget,
    FileMetadata,
    ParsedURL,
    ResolveError,
    URLType,
    VideoInfo,
)
from sp_dl.resolver.base import Resolver

logger = logging.getLogger(__name__)

# Patterns to find video URLs in stream.aspx HTML/JS
VIDEO_URL_PATTERNS = [
    # Direct MP4 source in video element
    re.compile(r'<source[^>]+src="([^"]+\.mp4[^"]*)"', re.IGNORECASE),
    # mediaSources JSON
    re.compile(r'"mediaSources"\s*:\s*\[([^\]]+)\]', re.IGNORECASE),
    # videoManifestUrl
    re.compile(r'"(?:videoManifestUrl|manifestUrl)"\s*:\s*"([^"]+)"', re.IGNORECASE),
    # Direct download URL in page config
    re.compile(r'"(?:downloadUrl|directUrl|blobUrl)"\s*:\s*"([^"]+)"', re.IGNORECASE),
    # .ism manifest
    re.compile(r'(https?://[^"\']+\.ism/manifest[^"\']*)', re.IGNORECASE),
    # Blob storage URL with token
    re.compile(
        r'(https?://[^"\']*\.blob\.core\.windows\.net/[^"\']+)',
        re.IGNORECASE,
    ),
]


class StreamPageResolver(Resolver):
    """Resolve videos by parsing the stream.aspx page HTML or using download.aspx fallback."""

    def can_handle(self, parsed: ParsedURL) -> bool:
        return parsed.url_type == URLType.STREAM_ASPX

    async def resolve(self, parsed: ParsedURL, client: httpx.AsyncClient) -> DownloadTarget:
        """Resolve stream.aspx video to a downloadable URL.

        Strategy:
        1. Fetch stream.aspx HTML and extract g_fileInfo
        2. If isDownloadBlocked, raise DownloadBlockedError (caller handles OAuth2 flow)
        3. Otherwise, try to extract embedded video URL or fall back to download.aspx
        """
        # Try to extract video URL from the page HTML
        video_url = None
        html = ""
        try:
            response = await client.get(
                parsed.original_url,
                headers={"Accept": "text/html"},
            )

            if response.status_code == 200:
                html = response.text

                # Check if download is blocked by admin policy
                file_info = self._parse_g_file_info(html)
                if file_info and file_info.get("isDownloadBlocked"):
                    logger.info("Download blocked by admin policy — media stream required")
                    raise DownloadBlockedError(
                        "SharePoint admin has blocked direct file downloads for this site. "
                        "OAuth2 authentication is required to stream the video."
                    )

                video_url = self._extract_video_url(html)
                metadata = self._extract_metadata(html, parsed)
            else:
                metadata = self._default_metadata(parsed)
        except DownloadBlockedError:
            raise
        except httpx.HTTPError:
            metadata = self._default_metadata(parsed)

        if video_url:
            # Determine if this is a manifest or direct URL
            is_manifest = any(x in video_url.lower() for x in [".ism/manifest", ".mpd", ".m3u8"])
            return DownloadTarget(
                metadata=metadata,
                download_url=video_url,
                requires_auth_headers="blob.core.windows.net" not in video_url,
                is_manifest=is_manifest,
            )

        # Fallback: use download.aspx?SourceUrl= which reliably downloads any file
        if parsed.server_relative_path:
            site_path = parsed.site_path or ""
            download_url = SP_DOWNLOAD_BY_PATH.format(
                tenant_domain=parsed.tenant_domain,
                site_path=site_path,
                server_relative_path=quote(parsed.server_relative_path, safe="/"),
            )
            logger.info(f"Using download.aspx fallback for stream video: {download_url}")
            return DownloadTarget(
                metadata=metadata,
                download_url=download_url,
                requires_auth_headers=True,
            )

        raise ResolveError(
            "Could not extract video URL from stream.aspx page and no file path available. "
            "Try using --cookies with a fresh cookie export."
        )

    def _parse_g_file_info(self, html: str) -> dict | None:
        """Parse var g_fileInfo = {...}; from the page HTML."""
        match = re.search(r"var\s+g_fileInfo\s*=\s*(\{.+?\})\s*;", html, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _extract_video_url(self, html: str) -> str | None:
        """Extract the video URL from stream.aspx HTML."""
        for pattern in VIDEO_URL_PATTERNS:
            match = pattern.search(html)
            if match:
                url = match.group(1)
                # Clean up escaped URLs
                url = url.replace("\\u002f", "/").replace("\\/", "/")
                if url.startswith("http"):
                    return url

        # Try parsing embedded JSON configurations
        return self._extract_from_json_config(html)

    def _extract_from_json_config(self, html: str) -> str | None:
        """Try to find video URL in embedded JSON/JavaScript objects."""
        # Look for script tags with JSON-like content
        soup = BeautifulSoup(html, "lxml")
        scripts = soup.find_all("script")

        for script in scripts:
            text = script.string or ""
            # Look for media configuration objects
            json_pattern = re.compile(
                r'\{[^{}]*"(?:url|src|source)"[^{}]*"(https?://[^"]+)"[^{}]*\}',
                re.IGNORECASE,
            )
            match = json_pattern.search(text)
            if match:
                url = match.group(1)
                if any(ext in url.lower() for ext in [".mp4", ".ism", ".m3u8", ".mpd", "blob"]):
                    return url

        # Look for data attributes
        video_elements = soup.find_all(attrs={"data-mediasources": True})
        for elem in video_elements:
            sources = elem.get("data-mediasources", "")
            try:
                sources_data = json.loads(sources)
                if isinstance(sources_data, list) and sources_data:
                    return sources_data[0].get("url") or sources_data[0].get("src")
            except (json.JSONDecodeError, AttributeError):
                pass

        return None

    def _extract_metadata(self, html: str, parsed: ParsedURL) -> FileMetadata:
        """Extract file metadata from the stream.aspx page."""
        soup = BeautifulSoup(html, "lxml")

        # Try to get title from page
        title_tag = soup.find("title")
        title = title_tag.string.strip() if title_tag and title_tag.string else None

        # Default name from path
        name = "video.mp4"
        if parsed.server_relative_path:
            name = Path(parsed.server_relative_path).name
        elif title:
            name = title if "." in title else f"{title}.mp4"

        # Try to find file size and duration in page data
        size_bytes = 0
        video_info = None

        # Look for duration in meta or data attributes
        duration_match = re.search(r'"duration"\s*:\s*(\d+)', html)
        if duration_match:
            video_info = VideoInfo(duration_ms=int(duration_match.group(1)))

        return FileMetadata(
            name=name,
            size_bytes=size_bytes,
            content_type="video/mp4",
            server_relative_path=parsed.server_relative_path,
            video_info=video_info,
        )

    def _default_metadata(self, parsed: ParsedURL) -> FileMetadata:
        """Build default metadata when page parsing fails."""
        name = "video.mp4"
        if parsed.server_relative_path:
            name = Path(parsed.server_relative_path).name
        return FileMetadata(
            name=name,
            size_bytes=0,
            content_type="video/mp4",
            server_relative_path=parsed.server_relative_path,
        )
