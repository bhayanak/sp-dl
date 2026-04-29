"""Tests for Doc.aspx URL parser."""

from __future__ import annotations

import pytest

from sp_dl.models import URLParseError, URLType
from sp_dl.url_parser.doc_aspx import DocAspxParser


class TestDocAspxParser:
    def setup_method(self):
        self.parser = DocAspxParser()

    def test_can_parse_doc_aspx(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/Doc.aspx?sourcedoc={abc-123}"
        assert self.parser.can_parse(url) is True

    def test_cannot_parse_stream_aspx(self):
        url = "https://contoso.sharepoint.com/_layouts/15/stream.aspx?id=/f.mp4"
        assert self.parser.can_parse(url) is False

    def test_cannot_parse_no_sourcedoc(self):
        url = "https://contoso.sharepoint.com/_layouts/15/Doc.aspx?id=/f.mp4"
        assert self.parser.can_parse(url) is False

    def test_parse_with_site_path(self):
        url = "https://contoso.sharepoint.com/sites/Team/_layouts/15/Doc.aspx?sourcedoc={e9b3c7f1-a2b4-4c5d-9e6f-7a8b9c0d1e2f}"
        result = self.parser.parse(url)

        assert result.url_type == URLType.DOC_ASPX
        assert result.tenant == "contoso"
        assert result.tenant_domain == "contoso.sharepoint.com"
        assert result.site_path == "/sites/Team"
        assert result.source_doc_guid == "e9b3c7f1-a2b4-4c5d-9e6f-7a8b9c0d1e2f"
        assert result.is_personal is False

    def test_parse_personal(self):
        url = "https://contoso-my.sharepoint.com/personal/user/_layouts/15/Doc.aspx?sourcedoc={abc-123}"
        result = self.parser.parse(url)

        assert result.tenant == "contoso"
        assert result.tenant_domain == "contoso-my.sharepoint.com"
        assert result.is_personal is True
        assert result.site_path == "/personal/user"

    def test_parse_no_site_path(self):
        url = "https://contoso.sharepoint.com/_layouts/15/Doc.aspx?sourcedoc={abc-123}"
        result = self.parser.parse(url)

        assert result.url_type == URLType.DOC_ASPX
        assert result.tenant == "contoso"

    def test_parse_guid_without_braces(self):
        url = "https://contoso.sharepoint.com/sites/T/_layouts/15/Doc.aspx?sourcedoc=e9b3c7f1-a2b4-4c5d-9e6f-7a8b9c0d1e2f"
        result = self.parser.parse(url)

        assert result.source_doc_guid == "e9b3c7f1-a2b4-4c5d-9e6f-7a8b9c0d1e2f"

    def test_manual_parse_fallback(self):
        # Use a URL that won't match the regex but has sourcedoc param
        url = (
            "https://contoso.sharepoint.com/_layouts/15/Doc.aspx?sourcedoc={abc-123}&action=default"
        )
        result = self.parser.parse(url)
        assert result.url_type == URLType.DOC_ASPX

    def test_manual_parse_non_sharepoint_raises(self):
        url = "https://example.com/_layouts/15/Doc.aspx?sourcedoc={abc}"
        # This won't match regex either
        with pytest.raises(URLParseError, match="Not a SharePoint"):
            self.parser._manual_parse(url)

    def test_manual_parse_no_sourcedoc_raises(self):
        url = "https://contoso.sharepoint.com/_layouts/15/Doc.aspx?action=default"
        with pytest.raises(URLParseError, match="No 'sourcedoc' parameter"):
            self.parser._manual_parse(url)

    def test_manual_parse_with_sites(self):
        url = "https://contoso.sharepoint.com/sites/Marketing/_layouts/15/Doc.aspx?sourcedoc={guid}"
        result = self.parser._manual_parse(url)
        assert result.site_path == "/sites/Marketing"

    def test_manual_parse_with_personal(self):
        url = (
            "https://contoso-my.sharepoint.com/personal/john/_layouts/15/Doc.aspx?sourcedoc={guid}"
        )
        result = self.parser._manual_parse(url)
        assert result.site_path == "/personal/john"
        assert result.is_personal is True

    def test_can_parse_case_insensitive(self):
        url = "https://contoso.sharepoint.com/_layouts/15/Doc.aspx?SOURCEDOC={abc}"
        assert self.parser.can_parse(url) is True
