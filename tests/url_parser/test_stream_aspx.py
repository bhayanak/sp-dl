"""Tests for URL parser — stream.aspx URLs."""

from __future__ import annotations

from sp_dl.models import URLType
from sp_dl.url_parser.stream_aspx import StreamAspxParser


class TestStreamAspxParser:
    def setup_method(self):
        self.parser = StreamAspxParser()

    def test_can_parse_stream_aspx_url(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/stream.aspx?id=/sites/Team/Shared%20Documents/demo.mp4"
        assert self.parser.can_parse(url) is True

    def test_cannot_parse_sharing_link(self):
        url = "https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJk"
        assert self.parser.can_parse(url) is False

    def test_parse_basic_stream_url(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/stream.aspx?id=/sites/Team/Shared%20Documents/demo.mp4"
        result = self.parser.parse(url)

        assert result.url_type == URLType.STREAM_ASPX
        assert result.tenant == "contoso"
        assert result.tenant_domain == "contoso.sharepoint.com"
        assert result.site_path == "/sites/Team"
        assert result.server_relative_path == "/sites/Team/Shared Documents/demo.mp4"
        assert result.is_personal is False

    def test_parse_personal_stream_url(self):
        url = "https://contoso-my.sharepoint.com/personal/john_contoso_com/_layouts/15/stream.aspx?id=/personal/john_contoso_com/Documents/recording.mp4"
        result = self.parser.parse(url)

        assert result.url_type == URLType.STREAM_ASPX
        assert result.tenant == "contoso"
        assert result.tenant_domain == "contoso-my.sharepoint.com"
        assert result.is_personal is True
        assert result.server_relative_path == "/personal/john_contoso_com/Documents/recording.mp4"

    def test_parse_url_with_extra_params(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/stream.aspx?id=/sites/Team/Shared%20Documents/video.mp4&referrer=StreamWebApp"
        result = self.parser.parse(url)

        assert result.server_relative_path == "/sites/Team/Shared Documents/video.mp4"

    def test_parse_url_with_spaces_in_path(self):
        url = "https://contoso.sharepoint.com/sites/My%20Team/_layouts/15/stream.aspx?id=/sites/My%20Team/Shared%20Documents/My%20Video.mp4"
        result = self.parser.parse(url)

        assert "My Video.mp4" in result.server_relative_path
