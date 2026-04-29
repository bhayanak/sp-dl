"""Core download engine with chunked streaming, resume, and retry."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from sp_dl.constants import CHUNK_SIZE, MAX_RETRIES, RETRY_BACKOFF_BASE
from sp_dl.models import (
    DownloadError,
    DownloadResult,
    DownloadStatus,
    DownloadTarget,
    ThrottleError,
)

logger = logging.getLogger(__name__)


async def download_file(
    client: httpx.AsyncClient,
    target: DownloadTarget,
    output_path: Path,
    progress_callback: Callable[[int], None] | None = None,
    limit_rate: int | None = None,
    no_overwrites: bool = False,
) -> DownloadResult:
    """
    Download a file with resume support, retry logic, and progress reporting.

    Args:
        client: Authenticated HTTP client.
        target: Resolved download target.
        output_path: Final output file path.
        progress_callback: Called with bytes written after each chunk.
        limit_rate: Max download speed in bytes/second. None = unlimited.
        no_overwrites: Skip if output file already exists.

    Returns:
        DownloadResult with download statistics.
    """
    if no_overwrites and output_path.exists():
        logger.info(f"File already exists, skipping: {output_path}")
        target.status = DownloadStatus.SKIPPED
        return DownloadResult(
            target=target,
            output_path=output_path,
            bytes_downloaded=0,
            elapsed_seconds=0.0,
        )

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.monotonic()
    target.status = DownloadStatus.DOWNLOADING

    try:
        result_path = await _download_with_resume(
            client=client,
            url=target.download_url,
            output_path=output_path,
            expected_size=target.metadata.size_bytes or None,
            expected_content_type=target.metadata.content_type,
            requires_auth=target.requires_auth_headers,
            progress_callback=progress_callback,
            limit_rate=limit_rate,
        )

        elapsed = time.monotonic() - start_time
        final_size = result_path.stat().st_size
        target.status = DownloadStatus.COMPLETED

        return DownloadResult(
            target=target,
            output_path=result_path,
            bytes_downloaded=final_size,
            elapsed_seconds=elapsed,
            resumed=_part_path(output_path).exists(),
        )

    except Exception as e:
        target.status = DownloadStatus.FAILED
        raise DownloadError(f"Download failed: {e}") from e


async def _download_with_resume(
    client: httpx.AsyncClient,
    url: str,
    output_path: Path,
    expected_size: int | None,
    expected_content_type: str | None,
    requires_auth: bool,
    progress_callback: Callable[[int], None] | None,
    limit_rate: int | None,
) -> Path:
    """Core download loop with resume and retry."""
    part_path = _part_path(output_path)

    for attempt in range(MAX_RETRIES):
        try:
            return await _do_download(
                client=client,
                url=url,
                output_path=output_path,
                part_path=part_path,
                expected_size=expected_size,
                expected_content_type=expected_content_type,
                requires_auth=requires_auth,
                progress_callback=progress_callback,
                limit_rate=limit_rate,
            )
        except ThrottleError:
            if attempt == MAX_RETRIES - 1:
                raise
            logger.warning(f"Throttled, retrying... ({attempt + 1}/{MAX_RETRIES})")
            await asyncio.sleep(RETRY_BACKOFF_BASE**attempt)
        except httpx.HTTPError as e:
            if attempt == MAX_RETRIES - 1:
                raise DownloadError(f"Download failed after {MAX_RETRIES} retries: {e}") from e
            wait = RETRY_BACKOFF_BASE**attempt
            logger.warning(f"HTTP error: {e}. Retrying in {wait}s... ({attempt + 1}/{MAX_RETRIES})")
            await asyncio.sleep(wait)

    raise DownloadError("Download failed: exhausted retries")


async def _do_download(
    client: httpx.AsyncClient,
    url: str,
    output_path: Path,
    part_path: Path,
    expected_size: int | None,
    expected_content_type: str | None,
    requires_auth: bool,
    progress_callback: Callable[[int], None] | None,
    limit_rate: int | None,
) -> Path:
    """Execute a single download attempt."""
    start_byte = 0
    if part_path.exists():
        start_byte = part_path.stat().st_size
        logger.info(f"Resuming from byte {start_byte}")

    headers: dict[str, str] = {}
    if start_byte > 0:
        headers["Range"] = f"bytes={start_byte}-"

    # If the URL is pre-authenticated, don't send auth headers
    if not requires_auth:
        # Create a clean client without auth for pre-auth URLs
        download_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=300.0),
            follow_redirects=True,
        )
    else:
        download_client = client

    try:
        async with download_client.stream("GET", url, headers=headers) as response:
            # Handle throttling
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "30"))
                logger.warning(f"Throttled. Waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                raise ThrottleError("Rate limited by SharePoint")

            if response.status_code == 416:
                # Range not satisfiable — file already complete
                if part_path.exists():
                    part_path.rename(output_path)
                    return output_path
                raise DownloadError("Range not satisfiable and no partial file exists")

            if response.status_code == 200 and start_byte > 0:
                # Server doesn't support Range — restart
                logger.warning("Server doesn't support resume, restarting download")
                start_byte = 0
                mode = "wb"
            elif response.status_code == 206:
                # Partial content — append
                mode = "ab"
            elif response.status_code == 200:
                mode = "wb"
            elif response.status_code in (401, 403):
                from sp_dl.models import AccessDeniedError

                raise AccessDeniedError(
                    f"Access denied (HTTP {response.status_code}). Credentials may have expired."
                )
            else:
                response.raise_for_status()
                mode = "wb"

            # Report resumed bytes to progress
            if start_byte > 0 and progress_callback:
                progress_callback(start_byte)

            # Validate response content type for video downloads
            resp_content_type = response.headers.get("content-type", "")
            if (
                expected_content_type
                and "video/" in expected_content_type
                and "text/html" in resp_content_type
            ):
                # We got HTML instead of video — the URL is wrong
                raise DownloadError(
                    "Server returned HTML instead of video content. "
                    "The download URL may be incorrect or require different authentication."
                )

            # Get actual content length from server
            server_content_length = response.headers.get("content-length")
            if server_content_length:
                server_size = int(server_content_length)
                # Warn if server says file is suspiciously small for a video
                if (
                    expected_content_type
                    and "video/" in expected_content_type
                    and server_size < 1_000_000  # less than 1MB for a video
                    and expected_size
                    and expected_size > 1_000_000
                ):
                    logger.warning(
                        f"Server content-length ({server_size:,}) much smaller than "
                        f"expected ({expected_size:,}). Download URL may be wrong."
                    )

            # Stream the response
            with open(part_path, mode) as f:
                bytes_since_rate_check = 0
                rate_check_time = time.monotonic()

                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    f.write(chunk)
                    chunk_size = len(chunk)

                    if progress_callback:
                        progress_callback(chunk_size)

                    # Rate limiting
                    if limit_rate:
                        bytes_since_rate_check += chunk_size
                        elapsed = time.monotonic() - rate_check_time

                        if elapsed > 0:
                            current_rate = bytes_since_rate_check / elapsed
                            if current_rate > limit_rate:
                                sleep_time = (bytes_since_rate_check / limit_rate) - elapsed
                                if sleep_time > 0:
                                    await asyncio.sleep(sleep_time)
                                bytes_since_rate_check = 0
                                rate_check_time = time.monotonic()
    finally:
        if not requires_auth and download_client is not client:
            await download_client.aclose()

    # Integrity check
    actual_size = part_path.stat().st_size
    if expected_size and expected_size > 0 and actual_size != expected_size:
        raise DownloadError(
            f"Size mismatch: expected {expected_size:,} bytes, got {actual_size:,} bytes"
        )

    # Success — rename .part to final
    part_path.rename(output_path)
    return output_path


def _part_path(output_path: Path) -> Path:
    """Get the .part file path for a given output path."""
    return output_path.with_suffix(output_path.suffix + ".part")


def parse_rate_limit(rate_str: str | None) -> int | None:
    """Parse a rate limit string like '5M' or '500K' into bytes/second."""
    if not rate_str:
        return None

    rate_str = rate_str.strip().upper()
    multipliers = {
        "K": 1024,
        "M": 1024 * 1024,
        "G": 1024 * 1024 * 1024,
    }

    for suffix, multiplier in multipliers.items():
        if rate_str.endswith(suffix):
            try:
                return int(float(rate_str[:-1]) * multiplier)
            except ValueError:
                return None

    try:
        return int(rate_str)
    except ValueError:
        return None
