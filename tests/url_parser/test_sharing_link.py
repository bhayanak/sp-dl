"""Tests for sharing link parser."""

from __future__ import annotations

import pytest

from sp_dl.models import URLParseError, URLType
from sp_dl.url_parser.sharing_link import SharingLinkParser


class TestSharingLinkParser:
    def setup_method(self):
        self.parser = SharingLinkParser()

    def test_can_parse_video_sharing_link(self):
        url = "https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJkLmNoPqRsTu"
        assert self.parser.can_parse(url) is True

    def test_can_parse_binary_sharing_link(self):
        url = "https://contoso.sharepoint.com/:b:/s/Team/EaBcDeFgHiJkLmNoPqRsTu"
        assert self.parser.can_parse(url) is True

    def test_cannot_parse_direct_path(self):
        url = "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/file.mp4"
        assert self.parser.can_parse(url) is False

    def test_parse_video_sharing_link(self):
        url = "https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJkLmNoPqRsTu"
        result = self.parser.parse(url)

        assert result.url_type == URLType.SHARING_LINK
        assert result.tenant == "contoso"
        assert result.tenant_domain == "contoso.sharepoint.com"
        assert result.sharing_token == "EaBcDeFgHiJkLmNoPqRsTu"
        assert result.is_personal is False

    def test_parse_personal_sharing_link(self):
        url = "https://contoso-my.sharepoint.com/:v:/s/personal/EaBcDeFgHiJk"
        result = self.parser.parse(url)

        assert result.url_type == URLType.SHARING_LINK
        assert result.is_personal is True

    # Manual parse fallback tests
    def test_manual_parse_non_sharepoint_raises(self):
        url = "https://example.com/:v:/s/Team/abc"
        with pytest.raises(URLParseError, match="Not a SharePoint"):
            self.parser._manual_parse(url)

    def test_manual_parse_short_path_raises(self):
        url = "https://contoso.sharepoint.com/:v:"
        with pytest.raises(URLParseError, match="Cannot parse sharing link"):
            self.parser._manual_parse(url)

    def test_manual_parse_fallback(self):
        # A URL that won't match the main regex but is parseable
        url = "https://contoso.sharepoint.com/:v:/s/Team/SomeToken123"
        result = self.parser._manual_parse(url)
        assert result.url_type == URLType.SHARING_LINK
        assert result.sharing_token == "SomeToken123"

    def test_cannot_parse_non_sharepoint(self):
        url = "https://example.com/path/to/file"
        assert self.parser.can_parse(url) is False
