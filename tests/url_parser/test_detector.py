"""Tests for URL type detection and dispatch."""

from __future__ import annotations

import pytest

from sp_dl.models import URLParseError, URLType
from sp_dl.url_parser.detector import detect_and_parse


class TestDetector:
    def test_detect_stream_aspx(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/stream.aspx?id=/sites/Team/Shared%20Documents/vid.mp4"
        result = detect_and_parse(url)
        assert result.url_type == URLType.STREAM_ASPX

    def test_detect_sharing_link(self):
        url = "https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJk"
        result = detect_and_parse(url)
        assert result.url_type == URLType.SHARING_LINK

    def test_detect_direct_path(self):
        url = "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/video.mp4"
        result = detect_and_parse(url)
        assert result.url_type == URLType.DIRECT_PATH

    def test_detect_doc_aspx(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/Doc.aspx?sourcedoc={E9B3C7F1-A2B4-4C5D-9E6F-7A8B9C0D1E2F}"
        result = detect_and_parse(url)
        assert result.url_type == URLType.DOC_ASPX

    def test_detect_onedrive_personal(self):
        url = "https://contoso-my.sharepoint.com/personal/john_contoso_com/Documents/video.mp4"
        result = detect_and_parse(url)
        assert result.url_type == URLType.ONEDRIVE_PERSONAL

    def test_empty_url_raises(self):
        with pytest.raises(URLParseError, match="Empty URL"):
            detect_and_parse("")

    def test_non_sharepoint_url_raises(self):
        with pytest.raises(URLParseError, match="Not a SharePoint URL"):
            detect_and_parse("https://www.google.com/video.mp4")

    def test_invalid_scheme_raises(self):
        with pytest.raises(URLParseError, match="Invalid URL scheme"):
            detect_and_parse("ftp://contoso.sharepoint.com/file.mp4")

    def test_unrecognized_sharepoint_url_raises(self):
        with pytest.raises(URLParseError, match="Unable to parse"):
            detect_and_parse("https://contoso.sharepoint.com/")
