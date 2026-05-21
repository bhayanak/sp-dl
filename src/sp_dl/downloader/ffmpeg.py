"""FFmpeg-based download for DASH/HLS adaptive streams."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from sp_dl.models import DownloadError

logger = logging.getLogger(__name__)


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is installed and accessible."""
    return shutil.which("ffmpeg") is not None


async def download_manifest(
    manifest_url: str,
    output_path: Path,
    cookies_file: Path | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> Path:
    """
    Download video from a DASH/HLS manifest using ffmpeg.

    Args:
        manifest_url: URL to the .mpd or .m3u8 manifest.
        output_path: Output file path.
        cookies_file: Optional Netscape cookie file for auth.
        progress_callback: Optional callback receiving bytes downloaded delta.

    Returns:
        Path to the downloaded file.
    """
    if not is_ffmpeg_available():
        raise DownloadError(
            "ffmpeg is required for adaptive streaming (DASH/HLS) downloads.\n"
            "Install ffmpeg: https://ffmpeg.org/download.html\n"
            "  macOS: brew install ffmpeg\n"
            "  Ubuntu: sudo apt install ffmpeg\n"
            "  Windows: winget install ffmpeg"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y", "-stats_period", "0.5", "-i", manifest_url]

    # Add cookie header if available
    if cookies_file and cookies_file.exists():
        cmd.extend(["-cookies", f"cookies={cookies_file}"])

    # Copy streams without re-encoding
    cmd.extend(["-c", "copy", str(output_path)])

    logger.info(f"Running ffmpeg for manifest download: {manifest_url}")
    logger.debug(f"ffmpeg command: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Parse ffmpeg progress from stderr
    stderr_lines: list[str] = []
    downloaded_bytes = 0
    while True:
        line = await process.stderr.readline()
        if not line:
            break
        text = line.decode(errors="replace").strip()
        stderr_lines.append(text)
        # Parse progress: "size=   12345kB time=00:01:23.45 ..."
        size_match = re.search(r"size=\s*(\d+)kB", text)
        if size_match and progress_callback:
            new_bytes = int(size_match.group(1)) * 1024
            delta = new_bytes - downloaded_bytes
            if delta > 0:
                progress_callback(delta)
                downloaded_bytes = new_bytes

    await process.wait()

    if process.returncode != 0:
        error_msg = "\n".join(stderr_lines[-10:])
        raise DownloadError(f"ffmpeg failed (exit code {process.returncode}):\n{error_msg}")

    if not output_path.exists():
        raise DownloadError("ffmpeg completed but output file not found")

    logger.info(f"ffmpeg download complete: {output_path}")
    return output_path
