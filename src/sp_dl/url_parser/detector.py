"""URL type detector and dispatch to appropriate parser."""

from __future__ import annotations

from sp_dl.models import ParsedURL, URLParseError
from sp_dl.url_parser.base import URLParser
from sp_dl.url_parser.direct_path import DirectPathParser
from sp_dl.url_parser.doc_aspx import DocAspxParser
from sp_dl.url_parser.sharing_link import SharingLinkParser
from sp_dl.url_parser.stream_aspx import StreamAspxParser

# Ordered by specificity — more specific patterns first
_PARSERS: list[URLParser] = [
    StreamAspxParser(),
    DocAspxParser(),
    SharingLinkParser(),
    DirectPathParser(),
]


def detect_and_parse(url: str) -> ParsedURL:
    """
    Auto-detect the SharePoint URL type and parse it.

    Tries each parser in order of specificity until one succeeds.

    Raises:
        URLParseError: If no parser can handle the URL.
    """
    url = url.strip()

    if not url:
        raise URLParseError("Empty URL provided")

    # Basic validation
    if not url.startswith(("http://", "https://")):
        raise URLParseError(f"Invalid URL scheme: {url}")

    if ".sharepoint.com" not in url.lower():
        raise URLParseError(f"Not a SharePoint URL: {url}")

    for parser in _PARSERS:
        if parser.can_parse(url):
            return parser.parse(url)

    raise URLParseError(
        f"Unable to parse SharePoint URL: {url}\n"
        "Supported patterns:\n"
        "  - stream.aspx?id=...\n"
        "  - /:v:/s/Site/Token (sharing links)\n"
        "  - /sites/Site/Library/file.ext (direct paths)\n"
        "  - Doc.aspx?sourcedoc={{guid}}\n"
        "  - /personal/user/Documents/file.ext (OneDrive)"
    )
