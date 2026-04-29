"""Test configuration and shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_cookies_file(tmp_path: Path) -> Path:
    """Create a sample Netscape cookies file."""
    content = """# Netscape HTTP Cookie File
# This is a generated file! Do not edit.

.sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\t77u/PD94bWwgdmVyc2lvbj0iMS4wIj8+example
.sharepoint.com\tTRUE\t/\tTRUE\t0\trtFa\texampleRtFaTokenValue123456
.sharepoint.com\tTRUE\t/\tTRUE\t0\tSPOIDCRL\texampleSPOIDCRLvalue
"""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(content)
    return cookie_file


@pytest.fixture
def graph_driveitem_response() -> dict:
    """Sample Graph API driveItem response."""
    return {
        "id": "01NKDM7HMO4KPXZQNBGLHYGX2OAFQZP43Q",
        "name": "Q3 All-Hands Recording.mp4",
        "size": 1524629504,
        "file": {
            "mimeType": "video/mp4",
        },
        "video": {
            "duration": 3600000,
            "width": 1920,
            "height": 1080,
            "bitrate": 3500000,
        },
        "lastModifiedDateTime": "2026-04-15T14:30:00Z",
        "createdBy": {
            "user": {
                "displayName": "John Smith",
                "id": "user-id-123",
            }
        },
        "parentReference": {
            "driveId": "drive-id-abc",
            "path": "/drive/root:/Shared Documents/Recordings",
        },
        "@microsoft.graph.downloadUrl": "https://tenant.sharepoint.com/_layouts/15/download.aspx?UniqueId=abc123&Translate=false&tempauth=eyJ0eX...",
    }


@pytest.fixture
def sp_rest_file_response() -> dict:
    """Sample SharePoint REST API file response."""
    return {
        "d": {
            "Name": "training-video.mp4",
            "Length": "524288000",
            "ContentType": "video/mp4",
            "ETag": '"{E9B3C7F1-A2B4-4C5D-9E6F-7A8B9C0D1E2F},1"',
            "TimeLastModified": "2026-04-10T09:15:00Z",
            "ServerRelativeUrl": "/sites/Team/Shared Documents/Videos/training-video.mp4",
            "UniqueId": "e9b3c7f1-a2b4-4c5d-9e6f-7a8b9c0d1e2f",
        }
    }
