"""Parser for stream.aspx URLs."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from sp_dl.constants import STREAM_ASPX_RE
from sp_dl.models import ParsedURL, URLParseError, URLType
from sp_dl.url_parser.base import URLParser


class StreamAspxParser(URLParser):
    """Parse stream.aspx?id=... URLs."""

    def can_parse(self, url: str) -> bool:
        return "_layouts/15/stream.aspx" in url.lower()

    def parse(self, url: str) -> ParsedURL:
        match = STREAM_ASPX_RE.search(url)
        if not match:
            # Fallback: manual parsing
            return self._manual_parse(url)

        tenant = match.group("tenant")
        site_path = match.group("site_path") or ""
        path = unquote(match.group("path"))

        is_personal = "-my" in tenant or "/personal/" in path
        tenant_domain = f"{tenant}.sharepoint.com"

        return ParsedURL(
            original_url=url,
            url_type=URLType.STREAM_ASPX,
            tenant=tenant.replace("-my", ""),
            tenant_domain=tenant_domain,
            site_path=site_path or None,
            server_relative_path=path,
            is_personal=is_personal,
        )

    def _manual_parse(self, url: str) -> ParsedURL:
        """Fallback parser using urllib."""
        parsed = urlparse(url)
        host = parsed.hostname or ""

        if ".sharepoint.com" not in host:
            raise URLParseError(f"Not a SharePoint URL: {url}")

        tenant = host.split(".sharepoint.com")[0]
        params = parse_qs(parsed.query)
        id_values = params.get("id", [])

        if not id_values:
            raise URLParseError(f"No 'id' parameter in stream.aspx URL: {url}")

        path = unquote(id_values[0])
        is_personal = "-my" in tenant or "/personal/" in path

        # Extract site path from the server-relative path
        site_path = None
        if "/sites/" in path:
            parts = path.split("/sites/")
            site_name = parts[1].split("/")[0]
            site_path = f"/sites/{site_name}"
        elif "/personal/" in path:
            parts = path.split("/personal/")
            personal_name = parts[1].split("/")[0]
            site_path = f"/personal/{personal_name}"

        return ParsedURL(
            original_url=url,
            url_type=URLType.STREAM_ASPX,
            tenant=tenant.replace("-my", ""),
            tenant_domain=f"{tenant}.sharepoint.com",
            site_path=site_path,
            server_relative_path=path,
            is_personal=is_personal,
        )
