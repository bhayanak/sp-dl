"""Parallel DASH segment downloader for fast adaptive stream downloads.

Instead of relying on ffmpeg (which downloads segments sequentially),
this module:
1. Fetches the DASH MPD manifest
2. Parses video/audio segment URLs
3. Downloads all segments concurrently
4. Concatenates fragments into the output file
5. Uses ffmpeg only for the final audio/video mux (fast, no network)
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import httpx

from sp_dl.models import DownloadError

logger = logging.getLogger(__name__)

# Namespace for DASH MPD
DASH_NS = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}

DEFAULT_CONCURRENCY = 10


@dataclass
class Segment:
    """A single downloadable segment."""

    url: str
    index: int
    is_init: bool = False


@dataclass
class Representation:
    """A media representation (quality level)."""

    rep_id: str
    content_type: str  # "video" or "audio"
    bandwidth: int
    width: int | None = None
    height: int | None = None
    base_url: str = ""
    segments: list[Segment] = field(default_factory=list)


async def download_dash_parallel(
    manifest_url: str,
    output_path: Path,
    cookies_file: Path | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    progress_callback: Callable[[int], None] | None = None,
) -> Path:
    """Download a DASH stream using parallel segment downloads.

    Args:
        manifest_url: URL to the DASH MPD manifest.
        output_path: Final output file path.
        cookies_file: Optional Netscape cookie file for auth.
        concurrency: Max concurrent segment downloads.
        progress_callback: Called with bytes downloaded per chunk.

    Returns:
        Path to the downloaded file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build cookies header from file
    cookie_header = _load_cookies_header(cookies_file) if cookies_file else ""

    headers = {}
    if cookie_header:
        headers["Cookie"] = cookie_header

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, read=120.0),
        follow_redirects=True,
        headers=headers,
    ) as client:
        # Step 1: Fetch and parse the MPD manifest
        logger.info(f"Fetching DASH manifest: {manifest_url}")
        resp = await client.get(manifest_url)
        if resp.status_code != 200:
            raise DownloadError(
                f"Failed to fetch DASH manifest (HTTP {resp.status_code}): "
                f"{resp.text[:200]}"
            )

        mpd_text = resp.text
        representations = _parse_mpd(mpd_text, manifest_url)

        if not representations:
            raise DownloadError("No playable representations found in DASH manifest")

        # Pick highest quality video and audio
        video_reps = [r for r in representations if r.content_type == "video"]
        audio_reps = [r for r in representations if r.content_type == "audio"]

        video_rep = max(video_reps, key=lambda r: r.bandwidth) if video_reps else None
        audio_rep = max(audio_reps, key=lambda r: r.bandwidth) if audio_reps else None

        if not video_rep and not audio_rep:
            raise DownloadError("No video or audio tracks found in DASH manifest")

        total_segments = (len(video_rep.segments) if video_rep else 0) + (
            len(audio_rep.segments) if audio_rep else 0
        )
        logger.info(
            f"DASH: {len(video_reps)} video reps, {len(audio_reps)} audio reps, "
            f"{total_segments} total segments to download"
        )
        if video_rep:
            logger.info(
                f"Selected video: {video_rep.width}x{video_rep.height} "
                f"@ {video_rep.bandwidth // 1000} kbps ({len(video_rep.segments)} segments)"
            )
        if audio_rep:
            logger.info(f"Selected audio: {audio_rep.bandwidth // 1000} kbps")

        # Step 2: Download segments in parallel
        semaphore = asyncio.Semaphore(concurrency)

        with tempfile.TemporaryDirectory(prefix="sp_dl_dash_") as tmp_dir:
            tmp = Path(tmp_dir)

            # Download video segments
            video_path = None
            if video_rep:
                video_path = tmp / "video.mp4"
                await _download_segments(
                    client, video_rep.segments, video_path, semaphore, progress_callback
                )

            # Download audio segments
            audio_path = None
            if audio_rep:
                audio_path = tmp / "audio.m4a"
                await _download_segments(
                    client, audio_rep.segments, audio_path, semaphore, progress_callback
                )

            # Step 3: Mux video + audio (or just copy if only one track)
            if video_path and audio_path:
                await _mux_av(video_path, audio_path, output_path)
            elif video_path:
                shutil.move(str(video_path), str(output_path))
            elif audio_path:
                shutil.move(str(audio_path), str(output_path))

    if not output_path.exists():
        raise DownloadError("Parallel DASH download completed but output file not found")

    logger.info(f"Parallel DASH download complete: {output_path}")
    return output_path


async def _download_segments(
    client: httpx.AsyncClient,
    segments: list[Segment],
    output_path: Path,
    semaphore: asyncio.Semaphore,
    progress_callback: Callable[[int], None] | None,
) -> None:
    """Download all segments concurrently and concatenate them in order."""
    # Pre-allocate result slots
    results: list[bytes | None] = [None] * len(segments)

    async def _fetch_one(seg: Segment, idx: int):
        async with semaphore:
            for attempt in range(3):
                try:
                    resp = await client.get(seg.url)
                    resp.raise_for_status()
                    data = resp.content
                    results[idx] = data
                    if progress_callback:
                        progress_callback(len(data))
                    return
                except (httpx.HTTPError, httpx.StreamError) as e:
                    if attempt == 2:
                        raise DownloadError(
                            f"Failed to download segment {seg.index} after 3 attempts: {e}"
                        ) from e
                    await asyncio.sleep(1 * (attempt + 1))

    # Launch all downloads concurrently
    tasks = [asyncio.create_task(_fetch_one(seg, i)) for i, seg in enumerate(segments)]
    await asyncio.gather(*tasks)

    # Write segments in order
    with output_path.open("wb") as f:
        for i, data in enumerate(results):
            if data is None:
                raise DownloadError(f"Segment {i} was not downloaded")
            f.write(data)


async def _mux_av(video_path: Path, audio_path: Path, output_path: Path) -> None:
    """Mux video and audio into final container using ffmpeg (no re-encoding)."""
    if not shutil.which("ffmpeg"):
        # If no ffmpeg, just use the video file (audio will be missing)
        logger.warning("ffmpeg not found — output will have video only (no audio mux)")
        shutil.move(str(video_path), str(output_path))
        return

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        error_text = stderr.decode(errors="replace")[-500:]
        raise DownloadError(f"ffmpeg mux failed (exit {process.returncode}): {error_text}")


def _parse_mpd(mpd_text: str, manifest_url: str) -> list[Representation]:
    """Parse a DASH MPD manifest and return representations with segment URLs."""
    try:
        root = ET.fromstring(mpd_text)
    except ET.ParseError as e:
        raise DownloadError(f"Failed to parse DASH manifest XML: {e}") from e

    # Determine the namespace
    ns = ""
    root_tag = root.tag
    ns_match = re.match(r"\{(.+?)\}", root_tag)
    if ns_match:
        ns = ns_match.group(1)

    def _find(elem, tag):
        if ns:
            return elem.findall(f"{{{ns}}}{tag}")
        return elem.findall(tag)

    def _find_one(elem, tag):
        if ns:
            return elem.find(f"{{{ns}}}{tag}")
        return elem.find(tag)

    representations: list[Representation] = []
    base_url = manifest_url.rsplit("?", 1)[0].rsplit("/", 1)[0] + "/"

    # Check for top-level BaseURL
    top_base = _find_one(root, "BaseURL")
    if top_base is not None and top_base.text:
        base_url = urljoin(manifest_url, top_base.text)

    for period in _find(root, "Period"):
        period_base = base_url
        pb = _find_one(period, "BaseURL")
        if pb is not None and pb.text:
            period_base = urljoin(base_url, pb.text)

        for adapt_set in _find(period, "AdaptationSet"):
            content_type = adapt_set.get("contentType", "")
            mime_type = adapt_set.get("mimeType", "")

            if not content_type:
                if "video" in mime_type:
                    content_type = "video"
                elif "audio" in mime_type:
                    content_type = "audio"

            adapt_base = period_base
            ab = _find_one(adapt_set, "BaseURL")
            if ab is not None and ab.text:
                adapt_base = urljoin(period_base, ab.text)

            # Get SegmentTemplate at AdaptationSet level
            seg_template = _find_one(adapt_set, "SegmentTemplate")

            for rep_elem in _find(adapt_set, "Representation"):
                rep_id = rep_elem.get("id", "0")
                bandwidth = int(rep_elem.get("bandwidth", "0"))
                width = int(rep_elem.get("width", "0")) or None
                height = int(rep_elem.get("height", "0")) or None

                # Determine content type from rep if not set
                rep_mime = rep_elem.get("mimeType", mime_type)
                if not content_type:
                    if "video" in rep_mime:
                        content_type = "video"
                    elif "audio" in rep_mime:
                        content_type = "audio"
                    else:
                        continue

                rep_base = adapt_base
                rb = _find_one(rep_elem, "BaseURL")
                if rb is not None and rb.text:
                    rep_base = urljoin(adapt_base, rb.text)

                # Get segments
                segments = _extract_segments(
                    rep_elem, adapt_set, seg_template, rep_base, manifest_url, rep_id, ns
                )

                if segments:
                    representations.append(
                        Representation(
                            rep_id=rep_id,
                            content_type=content_type,
                            bandwidth=bandwidth,
                            width=width,
                            height=height,
                            base_url=rep_base,
                            segments=segments,
                        )
                    )

    return representations


def _extract_segments(
    rep_elem,
    adapt_set,
    adapt_seg_template,
    base_url: str,
    manifest_url: str,
    rep_id: str,
    ns: str,
) -> list[Segment]:
    """Extract segment URLs from a Representation element."""

    def _find(elem, tag):
        if ns:
            return elem.findall(f"{{{ns}}}{tag}")
        return elem.findall(tag)

    def _find_one(elem, tag):
        if ns:
            return elem.find(f"{{{ns}}}{tag}")
        return elem.find(tag)

    segments: list[Segment] = []

    # Check for SegmentList (explicit segment URLs)
    seg_list = _find_one(rep_elem, "SegmentList")
    if seg_list is None:
        seg_list = _find_one(adapt_set, "SegmentList")
    if seg_list is not None:
        # Initialization segment
        init = _find_one(seg_list, "Initialization")
        if init is not None:
            init_url = init.get("sourceURL", "")
            if init_url:
                full_url = _resolve_segment_url(init_url, base_url, manifest_url)
                segments.append(Segment(url=full_url, index=0, is_init=True))

        # Media segments
        for i, seg_url_elem in enumerate(_find(seg_list, "SegmentURL")):
            media_url = seg_url_elem.get("media", "")
            if media_url:
                full_url = _resolve_segment_url(media_url, base_url, manifest_url)
                segments.append(Segment(url=full_url, index=i + 1))

        return segments

    # Check for SegmentTemplate
    seg_template = _find_one(rep_elem, "SegmentTemplate")
    if seg_template is None:
        seg_template = adapt_seg_template
    if seg_template is not None:
        init_template = seg_template.get("initialization", "")
        media_template = seg_template.get("media", "")
        start_number = int(seg_template.get("startNumber", "1"))

        # Initialization
        if init_template:
            init_url = _expand_template(init_template, rep_id, 0, 0)
            full_url = _resolve_segment_url(init_url, base_url, manifest_url)
            segments.append(Segment(url=full_url, index=0, is_init=True))

        # Get timeline or compute from duration
        timeline = _find_one(seg_template, "SegmentTimeline")
        if timeline is not None:
            seg_idx = start_number
            current_time = 0
            for s_elem in _find(timeline, "S"):
                t = int(s_elem.get("t", str(current_time)))
                d = int(s_elem.get("d", "0"))
                r = int(s_elem.get("r", "0"))

                current_time = t
                for _ in range(r + 1):
                    url = _expand_template(media_template, rep_id, seg_idx, current_time)
                    full_url = _resolve_segment_url(url, base_url, manifest_url)
                    segments.append(Segment(url=full_url, index=seg_idx))
                    current_time += d
                    seg_idx += 1
        else:
            # Duration-based: we don't know total duration, use a reasonable limit
            duration = int(seg_template.get("duration", "0"))
            if duration > 0 and media_template:
                # Can't determine total segments without knowing stream duration
                # Use a high number; server will 404 when done
                for i in range(start_number, start_number + 10000):
                    url = _expand_template(media_template, rep_id, i, (i - start_number) * duration)
                    full_url = _resolve_segment_url(url, base_url, manifest_url)
                    segments.append(Segment(url=full_url, index=i))

        return segments

    # No segment info — single file at base_url
    if base_url and base_url.startswith("http"):
        segments.append(Segment(url=base_url, index=0))

    return segments


def _expand_template(template: str, rep_id: str, number: int, time: int) -> str:
    """Expand a DASH SegmentTemplate URL pattern."""
    url = template.replace("$RepresentationID$", rep_id)
    url = url.replace("$Number$", str(number))
    url = url.replace("$Time$", str(time))
    # Handle format specifiers like $Number%05d$
    url = re.sub(r"\$Number%(\d+)d\$", lambda m: f"{number:0{int(m.group(1))}d}", url)
    url = re.sub(r"\$Time%(\d+)d\$", lambda m: f"{time:0{int(m.group(1))}d}", url)
    return url


def _resolve_segment_url(segment_url: str, base_url: str, manifest_url: str) -> str:
    """Resolve a segment URL relative to the base or manifest URL."""
    if segment_url.startswith("http"):
        return segment_url
    if segment_url.startswith("?"):
        # Query-only: append to base_url
        return base_url.split("?")[0] + segment_url
    return urljoin(base_url or manifest_url, segment_url)


def _load_cookies_header(cookies_file: Path) -> str:
    """Load a Netscape cookies.txt file and return a Cookie header string."""
    if not cookies_file.exists():
        return ""

    cookies = []
    try:
        for line in cookies_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name = parts[5]
                value = parts[6]
                cookies.append(f"{name}={value}")
    except (OSError, IndexError):
        return ""

    return "; ".join(cookies)
