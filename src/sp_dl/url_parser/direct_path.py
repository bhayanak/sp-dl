"""Parser for direct SharePoint document library paths."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from sp_dl.models import ParsedURL, URLParseError, URLType
from sp_dl.url_parser.base import URLParser


class DirectPathParser(URLParser):
    """Parse direct file paths: /sites/Team/Shared Documents/file.mp4."""

    def can_parse(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path.lower()

        if ".sharepoint.com" not in host:
            return False
        # Must not be a special page
        if "/_layouts/" in path:
            return False
        if "/:" in path:
            return False
        # Must have a file extension
        if "." not in path.rsplit("/", 1)[-1]:
            return False
        # Must be under /sites/ or /teams/ or /personal/
        return any(x in path for x in ("/sites/", "/teams/", "/personal/"))

    def parse(self, url: str) -> ParsedURL:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = unquote(parsed.path)

        if ".sharepoint.com" not in host:
            raise URLParseError(f"Not a SharePoint URL: {url}")

        tenant = host.split(".sharepoint.com")[0]
        is_personal = "-my" in tenant or "/personal/" in path

        # Extract site path
        site_path = None
        if "/sites/" in path:
            parts = path.split("/sites/")
            site_name = parts[1].split("/")[0]
            site_path = f"/sites/{site_name}"
        elif "/teams/" in path:
            parts = path.split("/teams/")
            team_name = parts[1].split("/")[0]
            site_path = f"/teams/{team_name}"
        elif "/personal/" in path:
            parts = path.split("/personal/")
            personal_name = parts[1].split("/")[0]
            site_path = f"/personal/{personal_name}"

        url_type = URLType.ONEDRIVE_PERSONAL if is_personal else URLType.DIRECT_PATH

        return ParsedURL(
            original_url=url,
            url_type=url_type,
            tenant=tenant.replace("-my", ""),
            tenant_domain=f"{tenant}.sharepoint.com",
            site_path=site_path,
            server_relative_path=path,
            is_personal=is_personal,
        )
