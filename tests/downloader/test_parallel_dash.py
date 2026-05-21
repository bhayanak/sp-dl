"""Tests for parallel DASH segment downloader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sp_dl.downloader.parallel_dash import (
    Representation,
    Segment,
    _expand_template,
    _load_cookies_header,
    _parse_mpd,
    _resolve_segment_url,
    download_dash_parallel,
)
from sp_dl.models import DownloadError


class TestMPDParsing:
    def test_parse_simple_segment_list(self):
        """Parse MPD with explicit SegmentList."""
        mpd = """\
<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet contentType="video" mimeType="video/mp4">
      <Representation id="1" bandwidth="5000000" width="1920" height="1080">
        <BaseURL>https://media.svc.ms/video/</BaseURL>
        <SegmentList>
          <Initialization sourceURL="init.mp4"/>
          <SegmentURL media="seg-1.m4s"/>
          <SegmentURL media="seg-2.m4s"/>
          <SegmentURL media="seg-3.m4s"/>
        </SegmentList>
      </Representation>
    </AdaptationSet>
    <AdaptationSet contentType="audio" mimeType="audio/mp4">
      <Representation id="2" bandwidth="128000">
        <BaseURL>https://media.svc.ms/audio/</BaseURL>
        <SegmentList>
          <Initialization sourceURL="init.mp4"/>
          <SegmentURL media="seg-1.m4s"/>
        </SegmentList>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""
        reps = _parse_mpd(mpd, "https://example.com/manifest.mpd")
        assert len(reps) == 2

        video = [r for r in reps if r.content_type == "video"][0]
        assert video.bandwidth == 5000000
        assert video.width == 1920
        assert len(video.segments) == 4  # init + 3 media

        audio = [r for r in reps if r.content_type == "audio"][0]
        assert len(audio.segments) == 2  # init + 1 media

    def test_parse_segment_template_with_timeline(self):
        """Parse MPD with SegmentTemplate + SegmentTimeline."""
        mpd = """\
<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet contentType="video" mimeType="video/mp4">
      <SegmentTemplate initialization="init-$RepresentationID$.mp4"
                       media="seg-$RepresentationID$-$Number$.m4s"
                       startNumber="1">
        <SegmentTimeline>
          <S t="0" d="2000" r="2"/>
        </SegmentTimeline>
      </SegmentTemplate>
      <Representation id="v1" bandwidth="3000000" width="1280" height="720">
        <BaseURL>https://cdn.example.com/</BaseURL>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""
        reps = _parse_mpd(mpd, "https://example.com/manifest.mpd")
        assert len(reps) == 1

        video = reps[0]
        assert video.content_type == "video"
        # init + 3 segments (r=2 means repeat 2 additional times = 3 total)
        assert len(video.segments) == 4
        assert video.segments[0].is_init
        assert "init-v1" in video.segments[0].url
        assert "seg-v1-1" in video.segments[1].url

    def test_parse_empty_mpd(self):
        mpd = '<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011"></MPD>'
        reps = _parse_mpd(mpd, "https://example.com/m.mpd")
        assert reps == []

    def test_parse_invalid_xml(self):
        with pytest.raises(DownloadError, match="parse"):
            _parse_mpd("not xml at all", "https://x.com/m.mpd")

    def test_picks_highest_bandwidth(self):
        """Multiple representations — picks highest bandwidth."""
        mpd = """\
<?xml version="1.0"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet contentType="video" mimeType="video/mp4">
      <Representation id="low" bandwidth="500000" width="640" height="360">
        <BaseURL>https://cdn.example.com/low/</BaseURL>
        <SegmentList><SegmentURL media="seg.m4s"/></SegmentList>
      </Representation>
      <Representation id="high" bandwidth="5000000" width="1920" height="1080">
        <BaseURL>https://cdn.example.com/high/</BaseURL>
        <SegmentList><SegmentURL media="seg.m4s"/></SegmentList>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""
        reps = _parse_mpd(mpd, "https://example.com/m.mpd")
        video_reps = [r for r in reps if r.content_type == "video"]
        best = max(video_reps, key=lambda r: r.bandwidth)
        assert best.rep_id == "high"
        assert best.bandwidth == 5000000


class TestHelpers:
    def test_expand_template_basic(self):
        result = _expand_template("seg-$RepresentationID$-$Number$.m4s", "v1", 5, 10000)
        assert result == "seg-v1-5.m4s"

    def test_expand_template_formatted_number(self):
        result = _expand_template("seg-$Number%05d$.m4s", "v1", 42, 0)
        assert result == "seg-00042.m4s"

    def test_resolve_segment_url_absolute(self):
        url = _resolve_segment_url(
            "https://cdn.example.com/seg.m4s", "https://base.com/", "https://manifest.com/m.mpd"
        )
        assert url == "https://cdn.example.com/seg.m4s"

    def test_resolve_segment_url_query_only(self):
        url = _resolve_segment_url("?seg=1", "https://base.com/video", "https://m.com/m.mpd")
        assert url == "https://base.com/video?seg=1"

    def test_resolve_segment_url_relative(self):
        url = _resolve_segment_url("seg-1.m4s", "https://cdn.com/path/", "https://m.com/m.mpd")
        assert url == "https://cdn.com/path/seg-1.m4s"

    def test_load_cookies_header(self, tmp_path):
        cookie_file = tmp_path / "cookies.txt"
        cookie_file.write_text(
            "# Netscape HTTP Cookie File\n"
            ".sharepoint.com\tTRUE\t/\tTRUE\t0\tFedAuth\tabc123\n"
            ".sharepoint.com\tTRUE\t/\tTRUE\t0\trtFa\txyz789\n"
        )
        header = _load_cookies_header(cookie_file)
        assert "FedAuth=abc123" in header
        assert "rtFa=xyz789" in header

    def test_load_cookies_missing_file(self, tmp_path):
        assert _load_cookies_header(tmp_path / "nope.txt") == ""


class TestDownloadDashParallel:
    @pytest.mark.asyncio
    async def test_raises_on_manifest_fetch_failure(self):
        """Should raise DownloadError if manifest fetch returns non-200."""
        with patch("sp_dl.downloader.parallel_dash.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(
                return_value=AsyncMock(status_code=401, text="Unauthorized")
            )

            with pytest.raises(DownloadError, match="401"):
                await download_dash_parallel(
                    "https://media.svc.ms/manifest.mpd",
                    Path("/tmp/out.mp4"),
                )
