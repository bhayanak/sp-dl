"""FFmpeg-based download for DASH/HLS adaptive streams."""

from __future__ import annotations

import asyncio
import logging
import shutil
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
) -> Path:
    """
    Download video from a DASH/HLS manifest using ffmpeg.

    Args:
        manifest_url: URL to the .mpd or .m3u8 manifest.
        output_path: Output file path.
        cookies_file: Optional Netscape cookie file for auth.

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

    cmd = ["ffmpeg", "-y", "-i", manifest_url]

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

    _, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode(errors="replace")[-500:]
        raise DownloadError(f"ffmpeg failed (exit code {process.returncode}):\n{error_msg}")

    if not output_path.exists():
        raise DownloadError("ffmpeg completed but output file not found")

    logger.info(f"ffmpeg download complete: {output_path}")
    return output_path
