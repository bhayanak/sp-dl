"""Constants for sharepoint-dl: URL patterns, API endpoints, and defaults."""

from __future__ import annotations

import re

# ─── URL Pattern Regexes ──────────────────────────────────────────────────────

# stream.aspx?id=/sites/Team/Shared%20Documents/video.mp4
STREAM_ASPX_RE = re.compile(
    r"https?://(?P<tenant>[\w-]+(?:-my)?)"
    r"\.sharepoint\.com"
    r"(?P<site_path>/(?:sites|personal)/[^/]+)?"
    r"/_layouts/15/stream\.aspx\?.*?id=(?P<path>[^&]+)",
    re.IGNORECASE,
)

# Sharing links: /:v:/s/Team/EncodedId or /:b:/r/Team/EncodedId
SHARING_LINK_RE = re.compile(
    r"https?://(?P<tenant>[\w-]+(?:-my)?)"
    r"\.sharepoint\.com"
    r"/(?::(?P<type_code>[a-z]):/)?"
    r"(?P<scope>[srtg])"
    r"/(?P<site>[^/]+)"
    r"/(?P<token>[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

# Direct document library path: /sites/Team/Shared Documents/folder/file.ext
DIRECT_PATH_RE = re.compile(
    r"https?://(?P<tenant>[\w-]+(?:-my)?)"
    r"\.sharepoint\.com"
    r"(?P<path>/(?:sites|teams)/[^?#]+\.\w+)",
    re.IGNORECASE,
)

# OneDrive personal: /personal/user_domain/Documents/file.ext
ONEDRIVE_PERSONAL_RE = re.compile(
    r"https?://(?P<tenant>[\w-]+)-my"
    r"\.sharepoint\.com"
    r"(?P<path>/personal/[^?#]+\.\w+)",
    re.IGNORECASE,
)

# Doc.aspx?sourcedoc={guid}
DOC_ASPX_RE = re.compile(
    r"https?://(?P<tenant>[\w-]+(?:-my)?)"
    r"\.sharepoint\.com"
    r"(?P<site_path>/(?:sites|personal)/[^/]+)?"
    r"/_layouts/15/Doc\.aspx\?.*?sourcedoc=\{?(?P<guid>[0-9a-fA-F-]+)\}?",
    re.IGNORECASE,
)

# ─── API Endpoints ────────────────────────────────────────────────────────────

SP_REST_FILE_BY_PATH = (
    "https://{tenant_domain}{site_path}/_api/web"
    "/GetFileByServerRelativeUrl('{server_relative_path}')"
)

SP_REST_FILE_CONTENT = (
    "https://{tenant_domain}{site_path}/_api/web"
    "/GetFileByServerRelativeUrl('{server_relative_path}')/$value"
)

# download.aspx endpoint — reliable for all file types including videos
SP_DOWNLOAD_ASPX = (
    "https://{tenant_domain}{site_path}/_layouts/15/download.aspx"
    "?UniqueId={unique_id}&Translate=false&tempauth=1&ApiVersion=2.0"
)

# Fallback: download.aspx with SourceUrl — works when UniqueId not available
SP_DOWNLOAD_BY_PATH = (
    "https://{tenant_domain}{site_path}/_layouts/15/download.aspx?SourceUrl={server_relative_path}"
)

# v2.0 API (modern OneDrive-style API on SharePoint)
SP_V2_DRIVE = "https://{tenant_domain}{site_path}/_api/v2.0/drive"
SP_V2_DRIVE_ITEM_BY_PATH = (
    "https://{tenant_domain}{site_path}/_api/v2.0/drive/root:/{drive_relative_path}:"
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SHARES_ITEM = GRAPH_BASE + "/shares/{encoded}/driveItem"
GRAPH_DRIVE_ITEM_CONTENT = GRAPH_BASE + "/drives/{drive_id}/items/{item_id}/content"

AZURE_AD_DEVICE_CODE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
AZURE_AD_TOKEN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
AZURE_AD_AUTHORIZE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"

# ─── Default Configuration ────────────────────────────────────────────────────

DEFAULT_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"  # Microsoft Office public client
# Microsoft Office first-party app — works on most enterprise tenants
OFFICE_CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
DEFAULT_SCOPES = ["https://graph.microsoft.com/Files.Read.All", "offline_access"]
SP_SCOPES = ["https://{tenant_domain}/AllSites.Read"]

# ─── Media Proxy (Stream video streaming) ─────────────────────────────────────

MEDIA_PROXY_MANIFEST_URL = (
    "https://{transform_host}/transform/videomanifest"
    "?provider=spo&farmid={farmid}&inputFormat=mp4&cs=fFNQTw"
    "&docid={docid}"
    "&access_token={access_token}"
    "&action=Access&part=index&format=dash&useScf=True&pretranscode=0"
)

# ─── Download Defaults ────────────────────────────────────────────────────────

CHUNK_SIZE = 1024 * 1024  # 1 MB
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2  # seconds
DEFAULT_TIMEOUT = 30.0  # seconds for API calls
DOWNLOAD_TIMEOUT = 300.0  # seconds for download stream

# ─── Cookie Names ─────────────────────────────────────────────────────────────

REQUIRED_COOKIES = ["FedAuth", "rtFa"]
OPTIONAL_COOKIES = ["SPOIDCRL"]

# ─── File Extensions ──────────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".m4v"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"}

# ─── Output Template Fields ───────────────────────────────────────────────────

TEMPLATE_FIELDS = {
    "filename",
    "title",
    "ext",
    "site",
    "folder",
    "size",
    "date",
    "author",
    "id",
}
