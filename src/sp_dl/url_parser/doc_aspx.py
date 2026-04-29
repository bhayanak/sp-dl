"""Parser for Doc.aspx?sourcedoc={guid} URLs."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from sp_dl.constants import DOC_ASPX_RE
from sp_dl.models import ParsedURL, URLParseError, URLType
from sp_dl.url_parser.base import URLParser


class DocAspxParser(URLParser):
    """Parse Doc.aspx?sourcedoc={guid} URLs."""

    def can_parse(self, url: str) -> bool:
        lower = url.lower()
        return "_layouts/15/doc.aspx" in lower and "sourcedoc" in lower

    def parse(self, url: str) -> ParsedURL:
        match = DOC_ASPX_RE.search(url)
        if not match:
            return self._manual_parse(url)

        tenant = match.group("tenant")
        site_path = match.group("site_path") or ""
        guid = match.group("guid")
        is_personal = "-my" in tenant

        return ParsedURL(
            original_url=url,
            url_type=URLType.DOC_ASPX,
            tenant=tenant.replace("-my", ""),
            tenant_domain=f"{tenant}.sharepoint.com",
            site_path=site_path or None,
            source_doc_guid=guid,
            is_personal=is_personal,
        )

    def _manual_parse(self, url: str) -> ParsedURL:
        """Fallback for Doc.aspx URLs."""
        parsed = urlparse(url)
        host = parsed.hostname or ""

        if ".sharepoint.com" not in host:
            raise URLParseError(f"Not a SharePoint URL: {url}")

        tenant = host.split(".sharepoint.com")[0]
        params = parse_qs(parsed.query)
        sourcedoc = params.get("sourcedoc", params.get("sourceDoc", [""]))

        if not sourcedoc or not sourcedoc[0]:
            raise URLParseError(f"No 'sourcedoc' parameter found: {url}")

        guid = sourcedoc[0].strip("{}")
        is_personal = "-my" in tenant

        # Try to extract site path
        path = parsed.path
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
            url_type=URLType.DOC_ASPX,
            tenant=tenant.replace("-my", ""),
            tenant_domain=f"{tenant}.sharepoint.com",
            site_path=site_path,
            source_doc_guid=guid,
            is_personal=is_personal,
        )
