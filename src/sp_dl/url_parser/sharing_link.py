"""Parser for SharePoint sharing links."""

from __future__ import annotations

from urllib.parse import urlparse

from sp_dl.constants import SHARING_LINK_RE
from sp_dl.models import ParsedURL, URLParseError, URLType
from sp_dl.url_parser.base import URLParser

# Sharing link type codes
TYPE_CODES = {
    "v": "video",
    "b": "binary",
    "w": "word",
    "x": "excel",
    "p": "powerpoint",
    "o": "onenote",
    "f": "folder",
    "u": "generic",
}


class SharingLinkParser(URLParser):
    """Parse sharing links like /:v:/s/Team/EncodedToken."""

    def can_parse(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path
        return ".sharepoint.com" in host and "/:" in path and ":/" in path

    def parse(self, url: str) -> ParsedURL:
        match = SHARING_LINK_RE.search(url)
        if not match:
            return self._manual_parse(url)

        tenant = match.group("tenant")
        token = match.group("token")
        site = match.group("site")
        is_personal = "-my" in tenant

        return ParsedURL(
            original_url=url,
            url_type=URLType.SHARING_LINK,
            tenant=tenant.replace("-my", ""),
            tenant_domain=f"{tenant}.sharepoint.com",
            site_path=f"/sites/{site}" if not is_personal else f"/personal/{site}",
            sharing_token=token,
            is_personal=is_personal,
        )

    def _manual_parse(self, url: str) -> ParsedURL:
        """Fallback parser for sharing links."""
        parsed = urlparse(url)
        host = parsed.hostname or ""

        if ".sharepoint.com" not in host:
            raise URLParseError(f"Not a SharePoint sharing link: {url}")

        tenant = host.split(".sharepoint.com")[0]
        path = parsed.path
        is_personal = "-my" in tenant

        # Extract the sharing token (last path segment)
        segments = [s for s in path.split("/") if s and not s.startswith(":")]
        if len(segments) < 2:
            raise URLParseError(f"Cannot parse sharing link structure: {url}")

        site = segments[-2] if len(segments) >= 2 else ""
        token = segments[-1]

        return ParsedURL(
            original_url=url,
            url_type=URLType.SHARING_LINK,
            tenant=tenant.replace("-my", ""),
            tenant_domain=f"{tenant}.sharepoint.com",
            site_path=f"/sites/{site}" if site else None,
            sharing_token=token,
            is_personal=is_personal,
        )
