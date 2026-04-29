"""Tests for direct path parser."""

from __future__ import annotations

from sp_dl.models import URLType
from sp_dl.url_parser.direct_path import DirectPathParser


class TestDirectPathParser:
    def setup_method(self):
        self.parser = DirectPathParser()

    def test_can_parse_sites_path(self):
        url = "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/video.mp4"
        assert self.parser.can_parse(url) is True

    def test_can_parse_teams_path(self):
        url = "https://contoso.sharepoint.com/teams/MyTeam/Documents/file.pdf"
        assert self.parser.can_parse(url) is True

    def test_cannot_parse_stream_aspx(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/stream.aspx?id=test"
        assert self.parser.can_parse(url) is False

    def test_cannot_parse_no_extension(self):
        url = "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/folder"
        assert self.parser.can_parse(url) is False

    def test_parse_direct_path(self):
        url = "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/Videos/training.mp4"
        result = self.parser.parse(url)

        assert result.url_type == URLType.DIRECT_PATH
        assert result.tenant == "contoso"
        assert result.tenant_domain == "contoso.sharepoint.com"
        assert result.site_path == "/sites/Team"
        assert result.server_relative_path == "/sites/Team/Shared Documents/Videos/training.mp4"
        assert result.is_personal is False

    def test_parse_onedrive_personal(self):
        url = "https://contoso-my.sharepoint.com/personal/john_contoso_com/Documents/video.mp4"
        result = self.parser.parse(url)

        assert result.url_type == URLType.ONEDRIVE_PERSONAL
        assert result.is_personal is True
        assert result.site_path == "/personal/john_contoso_com"

    def test_parse_url_with_nested_folders(self):
        url = "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/Level1/Level2/Level3/file.docx"
        result = self.parser.parse(url)

        assert "/Level1/Level2/Level3/file.docx" in result.server_relative_path

    def test_cannot_parse_non_sharepoint(self):
        url = "https://example.com/sites/Team/file.mp4"
        assert self.parser.can_parse(url) is False

    def test_cannot_parse_sharing_link(self):
        url = "https://contoso.sharepoint.com/:v:/s/Team/abc123"
        assert self.parser.can_parse(url) is False

    def test_cannot_parse_no_site_prefix(self):
        url = "https://contoso.sharepoint.com/random/path/file.mp4"
        assert self.parser.can_parse(url) is False

    def test_parse_non_sharepoint_raises(self):
        import pytest

        from sp_dl.models import URLParseError

        with pytest.raises(URLParseError, match="Not a SharePoint"):
            self.parser.parse("https://example.com/sites/t/file.mp4")

    def test_parse_teams_site_path(self):
        url = "https://contoso.sharepoint.com/teams/MyTeam/Shared%20Documents/doc.pptx"
        result = self.parser.parse(url)
        assert result.site_path == "/teams/MyTeam"

    def test_parse_personal_path(self):
        url = "https://contoso-my.sharepoint.com/personal/user_contoso_com/Documents/report.xlsx"
        result = self.parser.parse(url)
        assert result.site_path == "/personal/user_contoso_com"
        assert result.is_personal is True
