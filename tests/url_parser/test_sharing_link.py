"""Tests for sharing link parser."""

from __future__ import annotations

from sp_dl.models import URLType
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
