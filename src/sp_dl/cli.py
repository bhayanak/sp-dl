"""sp-dl CLI — SharePoint Video & File Downloader."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sp_dl import __version__

app = typer.Typer(
    name="sp-dl",
    help="Download videos and files from SharePoint — like yt-dlp for SharePoint.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Quick start:[/bold]\n\n"
        "  [dim]# Cookie-based (easiest):[/dim]\n"
        "  sp-dl download URL --cookies cookies.txt\n\n"
        "  [dim]# Auto-extract from browser:[/dim]\n"
        "  pip install 'sp-dl\\[browser-cookies]'\n"
        "  sp-dl download URL --cookies-from-browser chrome\n\n"
        "  [dim]# Show file info only:[/dim]\n"
        "  sp-dl download URL --info -c cookies.txt\n\n"
        "  [dim]# Batch download:[/dim]\n"
        "  sp-dl batch urls.txt -c cookies.txt\n\n"
        "[dim]Docs: https://github.com/sp-dl/sp-dl#readme[/dim]"
    ),
)
auth_app = typer.Typer(
    help="Manage authentication tokens.",
    epilog=(
        "[bold]Examples:[/bold]\n\n"
        "  [dim]# Cookie-based auth (recommended, no setup needed):[/dim]\n"
        "  sp-dl download URL --cookies cookies.txt\n\n"
        "  [dim]# OAuth login for enterprise tenants:[/dim]\n"
        "  sp-dl auth login --tenant contoso.onmicrosoft.com\n\n"
        "  [dim]# Check if you're logged in:[/dim]\n"
        "  sp-dl auth status"
    ),
)
app.add_typer(auth_app, name="auth")

console = Console()
err_console = Console(stderr=True)


def version_callback(value: bool):
    if value:
        console.print(f"sp-dl {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
):
    """sp-dl: Download videos and files from SharePoint."""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@app.command()
def download(
    url: str = typer.Argument(
        ...,
        help="SharePoint URL to download (stream.aspx, sharing link, direct path, etc).",
    ),
    cookies: Path | None = typer.Option(
        None,
        "--cookies",
        "-c",
        help="Path to Netscape-format cookie file (recommended auth method).",
    ),
    cookies_from_browser: str | None = typer.Option(
        None,
        "--cookies-from-browser",
        help="Extract cookies from browser: chrome, edge, firefox, brave.",
    ),
    output: str | None = typer.Option(
        None,
        "-o",
        "--output",
        help="Output filename or template, e.g. 'video.mp4' or '%(title)s.%(ext)s'.",
    ),
    info: bool = typer.Option(
        False,
        "--info",
        "-i",
        help="Show file metadata without downloading.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output metadata as JSON (implies --info).",
    ),
    no_overwrites: bool = typer.Option(
        False,
        "--no-overwrites",
        help="Skip download if output file already exists.",
    ),
    limit_rate: str | None = typer.Option(
        None,
        "--limit-rate",
        "-r",
        help="Limit download speed, e.g. '5M' for 5 MB/s, '500K' for 500 KB/s.",
    ),
    retries: int = typer.Option(
        5,
        "--retries",
        help="Number of download retries on failure.",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        "-t",
        help="Azure AD tenant (auto-detected from URL if not set).",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="Azure AD app client ID (only needed for OAuth/service account auth).",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="Azure AD app client secret (only needed for service account auth).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Verbose output.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Debug logging.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress all output except errors.",
    ),
):
    """Download a file from a SharePoint URL.

    [bold]Authentication[/bold] (pick one):

      [cyan]--cookies / -c[/cyan]       Netscape cookie file (easiest, recommended)
      [cyan]--cookies-from-browser[/cyan]  Auto-extract from Chrome/Edge/Firefox
      [cyan]sp-dl auth login[/cyan]     OAuth device code (enterprise tenants)

    [bold]Examples[/bold]:

      sp-dl download URL -c cookies.txt
      sp-dl download URL --cookies-from-browser chrome -o video.mp4
      sp-dl download URL --info -c cookies.txt
    """
    _setup_logging(verbose, debug, quiet)
    asyncio.run(
        _download_async(
            url=url,
            cookies=cookies,
            cookies_from_browser=cookies_from_browser,
            output=output,
            info_only=info or json_output,
            json_output=json_output,
            no_overwrites=no_overwrites,
            limit_rate=limit_rate,
            retries=retries,
            tenant=tenant,
            client_id=client_id,
            client_secret=client_secret,
            quiet=quiet,
        )
    )


@app.command("batch")
def batch_download(
    batch_file: Path = typer.Argument(..., help="File containing URLs (one per line)."),
    cookies: Path | None = typer.Option(None, "--cookies", "-c"),
    cookies_from_browser: str | None = typer.Option(None, "--cookies-from-browser"),
    output: str | None = typer.Option(None, "-o", "--output"),
    no_overwrites: bool = typer.Option(False, "--no-overwrites"),
    limit_rate: str | None = typer.Option(None, "--limit-rate", "-r"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
):
    """Download multiple URLs from a batch file."""
    _setup_logging(verbose, False, quiet)

    if not batch_file.exists():
        err_console.print(f"[red]Error:[/red] Batch file not found: {batch_file}")
        raise typer.Exit(1)

    urls = [
        line.strip()
        for line in batch_file.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not urls:
        err_console.print("[yellow]No URLs found in batch file.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold]Found {len(urls)} URLs to download[/bold]\n")

    for i, url in enumerate(urls, 1):
        console.print(f"[dim]({i}/{len(urls)})[/dim] {url[:80]}...")
        try:
            asyncio.run(
                _download_async(
                    url=url,
                    cookies=cookies,
                    cookies_from_browser=cookies_from_browser,
                    output=output,
                    info_only=False,
                    json_output=False,
                    no_overwrites=no_overwrites,
                    limit_rate=limit_rate,
                    retries=5,
                    tenant=None,
                    client_id=None,
                    client_secret=None,
                    quiet=quiet,
                )
            )
        except Exception as e:
            err_console.print(f"  [red]Failed:[/red] {e}")


@auth_app.command("login")
def auth_login(
    tenant: str = typer.Option(
        ...,
        "--tenant",
        "-t",
        help="Azure AD tenant, e.g. 'contoso.onmicrosoft.com' or 'contoso'.",
        prompt=("Enter your Azure AD tenant\n(e.g. 'contoso.onmicrosoft.com' or just 'contoso')"),
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="Azure AD app client ID (uses Azure CLI public client if not set).",
    ),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Use browser-based login instead of device code."
    ),
):
    """Log in using device code or browser flow.

    [bold]Examples[/bold]:

      sp-dl auth login --tenant contoso.onmicrosoft.com
      sp-dl auth login --tenant contoso -i   [dim](browser login)[/dim]

    [bold]Note[/bold]: Cookie-based auth (--cookies) does NOT require login.
    This is only needed for OAuth-based downloads.
    """
    # Normalize tenant: "contoso" -> "contoso.onmicrosoft.com"
    # Also handle "https://contoso.sharepoint.com" -> "contoso.onmicrosoft.com"
    normalized_tenant = _normalize_tenant(tenant)
    console.print(f"[dim]Using tenant: {normalized_tenant}[/dim]")
    asyncio.run(_auth_login_async(normalized_tenant, client_id, interactive))


@auth_app.command("status")
def auth_status():
    """Show current authentication status."""
    import time

    from sp_dl.auth.token_cache import TokenCache

    cache = TokenCache()
    if not cache.exists:
        console.print("[yellow]Not logged in.[/yellow] Run: sp-dl auth login")
        return

    data = cache.load()
    if not data:
        console.print("[yellow]Token cache is empty.[/yellow]")
        return

    expires_at = data.get("expires_at", 0)
    is_valid = time.time() < expires_at

    table = Table(title="Authentication Status")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Token cached", "[green]Yes[/green]")
    table.add_row(
        "Token valid",
        "[green]Yes[/green]" if is_valid else "[red]Expired[/red]",
    )
    table.add_row("Has refresh token", "Yes" if data.get("refresh_token") else "No")
    table.add_row("Cache path", str(cache.path))

    console.print(table)


@auth_app.command("logout")
def auth_logout():
    """Clear saved authentication tokens."""
    from sp_dl.auth.token_cache import TokenCache

    cache = TokenCache()
    if cache.exists:
        cache.clear()
        console.print("[green]✓[/green] Logged out. Token cache cleared.")
    else:
        console.print("[dim]No cached tokens found.[/dim]")


@app.command("quickstart")
def quickstart():
    """Show step-by-step guide to download your first file."""
    console.print()
    console.print(
        Panel(
            "[bold blue]📥 sp-dl Quick Start Guide[/bold blue]",
            border_style="blue",
        )
    )
    console.print()

    console.print("[bold]Step 1: Get your SharePoint URL[/bold]")
    console.print("  Open the video/file in SharePoint and copy the URL from your browser.")
    console.print()

    console.print("[bold]Step 2: Choose an authentication method[/bold]")
    console.print()

    table = Table(show_header=True, show_lines=True, expand=True)
    table.add_column("Method", style="bold cyan", width=20)
    table.add_column("Difficulty", width=10)
    table.add_column("Command", style="green")

    table.add_row(
        "Cookie file\n(recommended)",
        "Easy",
        (
            "1. Install browser extension 'Get cookies.txt LOCALLY'\n"
            "2. Go to your SharePoint site, click the extension, export\n"
            "3. sp-dl download URL --cookies cookies.txt"
        ),
    )
    table.add_row(
        "Auto-extract\nfrom browser",
        "Easy",
        (
            "1. pip install 'sp-dl[browser-cookies]'\n"
            "2. Close your browser completely\n"
            "3. sp-dl download URL --cookies-from-browser chrome"
        ),
    )
    table.add_row(
        "OAuth login\n(device code)",
        "Medium",
        (
            "1. sp-dl auth login --tenant YOUR_ORG\n"
            "2. Follow the device code prompt\n"
            "3. sp-dl download URL"
        ),
    )
    console.print(table)
    console.print()

    console.print("[bold]Step 3: Download![/bold]")
    console.print()
    console.print("  [dim]# With cookies (recommended):[/dim]")
    console.print("  sp-dl download URL --cookies cookies.txt")
    console.print()
    console.print("  [dim]# Custom output filename:[/dim]")
    console.print("  sp-dl download URL -c cookies.txt -o video.mp4")
    console.print()
    console.print("  [dim]# Just show file info:[/dim]")
    console.print("  sp-dl download URL --info -c cookies.txt")
    console.print()
    console.print("  [dim]# Multiple files:[/dim]")
    console.print("  sp-dl batch urls.txt -c cookies.txt")
    console.print()

    console.print("[bold]Supported URLs:[/bold]")
    console.print("  • stream.aspx videos (/_layouts/15/stream.aspx?id=...)")
    console.print("  • Sharing links (/:v:/s/Team/...)")
    console.print("  • Direct file paths (/sites/Team/Documents/file.mp4)")
    console.print("  • OneDrive personal (/personal/.../Documents/file.mp4)")
    console.print()

    console.print("[dim]Full docs: https://github.com/sp-dl/sp-dl#readme[/dim]")


# ─── Internal async functions ─────────────────────────────────────────────────


async def _download_async(
    url: str,
    cookies: Path | None,
    cookies_from_browser: str | None,
    output: str | None,
    info_only: bool,
    json_output: bool,
    no_overwrites: bool,
    limit_rate: str | None,
    retries: int,
    tenant: str | None,
    client_id: str | None,
    client_secret: str | None,
    quiet: bool,
) -> None:
    """Main async download pipeline."""
    from sp_dl.auth.session import build_session, create_auth_provider
    from sp_dl.config import SpDlConfig, resolve_output_path
    from sp_dl.downloader.engine import download_file, parse_rate_limit
    from sp_dl.downloader.ffmpeg import download_manifest, is_ffmpeg_available
    from sp_dl.downloader.progress import create_download_progress, format_size
    from sp_dl.models import DownloadBlockedError, SpDlError, URLType
    from sp_dl.resolver import resolve_download_target
    from sp_dl.url_parser import detect_and_parse

    config = SpDlConfig.load()

    # Header
    if not quiet:
        console.print(
            Panel(
                "[bold blue]📥 sp-dl[/bold blue] · SharePoint Downloader",
                border_style="blue",
            )
        )
        console.print()

    # Step 1: Parse URL
    if not quiet:
        console.print("[bold]🔗 Resolving URL...[/bold]")

    try:
        parsed = detect_and_parse(url)
    except SpDlError as e:
        err_console.print(f"[red]❌ URL Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not quiet:
        console.print(f"   Type:     {parsed.url_type.value}")
        console.print(f"   Tenant:   {parsed.tenant_domain}")
        if parsed.site_path:
            console.print(f"   Site:     {parsed.site_path}")
        console.print()

    # Step 2: Authenticate
    if not quiet:
        console.print("[bold]🔑 Authenticating...[/bold]")

    # Auto-detect tenant from the URL when not explicitly set
    effective_tenant = tenant or config.tenant
    if (not effective_tenant or effective_tenant == "common") and parsed.tenant_domain:
        # Extract Azure AD tenant from SharePoint domain
        # e.g. "contoso.sharepoint.com" -> "contoso.onmicrosoft.com"
        # For -my domains: "contoso-my.sharepoint.com" -> "contoso.onmicrosoft.com"
        domain_part = parsed.tenant_domain.split(".sharepoint.com")[0]
        domain_part = domain_part.removesuffix("-my")
        effective_tenant = f"{domain_part}.onmicrosoft.com"

    try:
        auth_provider = create_auth_provider(
            cookies_file=cookies or (Path(config.cookies_file) if config.cookies_file else None),
            cookies_from_browser=cookies_from_browser or config.cookies_from_browser or None,
            tenant=effective_tenant or "common",
            client_id=client_id or config.client_id or None,
            client_secret=client_secret,
        )
        client = await build_session(auth_provider)
    except SpDlError as e:
        err_console.print(f"[red]❌ Auth Error:[/red] {e}")
        err_console.print()
        err_console.print("[yellow]Tip:[/yellow] The easiest auth method is cookies:")
        err_console.print("  1. Log into SharePoint in your browser")
        err_console.print("  2. Export cookies (use 'Get cookies.txt' browser extension)")
        err_console.print("  3. Run: sp-dl download URL --cookies cookies.txt")
        err_console.print()
        err_console.print(
            "  Or auto-extract: pip install 'sp-dl\\[browser-cookies]' && "
            "sp-dl download URL --cookies-from-browser chrome"
        )
        raise typer.Exit(1) from None

    if not quiet:
        console.print(f"   Method:   {auth_provider.description}")
        console.print()

    # Step 3: Resolve
    try:
        target = await resolve_download_target(parsed, client)
    except DownloadBlockedError:
        # Download blocked by admin policy — use OAuth2 + media proxy streaming
        if not quiet:
            console.print(
                "[yellow]⚠ Download blocked by admin policy — "
                "switching to OAuth2 video streaming...[/yellow]"
            )
            console.print()
        target = await _resolve_via_media_stream(parsed, client, effective_tenant, quiet)
    except SpDlError as e:
        err_console.print(f"[red]❌ Resolve Error:[/red] {e}")
        await client.aclose()
        raise typer.Exit(1) from None

    # Display file info
    meta = target.metadata
    if not quiet:
        console.print("[bold]📄 File info:[/bold]")
        console.print(f"   Name:     {meta.name}")
        if meta.size_bytes:
            console.print(f"   Size:     {format_size(meta.size_bytes)}")
        if meta.content_type:
            console.print(f"   Type:     {meta.content_type}")
        if meta.modified_at:
            console.print(f"   Modified: {meta.modified_at.strftime('%Y-%m-%d %H:%M UTC')}")
        if meta.created_by:
            console.print(f"   Author:   {meta.created_by}")
        console.print()

    # Info-only mode
    if info_only:
        if json_output:
            info_dict = {
                "name": meta.name,
                "size_bytes": meta.size_bytes,
                "content_type": meta.content_type,
                "modified_at": meta.modified_at.isoformat() if meta.modified_at else None,
                "created_by": meta.created_by,
                "url_type": parsed.url_type.value,
                "tenant": parsed.tenant_domain,
                "site_path": parsed.site_path,
            }
            if meta.video_info:
                info_dict["video"] = {
                    "duration_ms": meta.video_info.duration_ms,
                    "width": meta.video_info.width,
                    "height": meta.video_info.height,
                }
            console.print(json.dumps(info_dict, indent=2, default=str))
        await client.aclose()
        return

    # Step 4: Determine output path
    output_template = output or config.output_template
    template_metadata = {
        "filename": meta.name,
        "title": Path(meta.name).stem,
        "ext": Path(meta.name).suffix.lstrip("."),
        "site": parsed.site_path.split("/")[-1] if parsed.site_path else "unknown",
        "folder": str(Path(meta.server_relative_path or "").parent.name) or "root",
        "size": format_size(meta.size_bytes),
        "date": meta.modified_at.strftime("%Y%m%d") if meta.modified_at else "unknown",
        "author": meta.created_by or "unknown",
        "id": meta.drive_item_id or "unknown",
    }

    output_path = resolve_output_path(output_template, template_metadata)

    # Step 5: Download
    if target.is_manifest:
        if not quiet:
            console.print("[bold]📥 Downloading via ffmpeg (adaptive stream)...[/bold]")
        if not is_ffmpeg_available():
            err_console.print(
                "[red]❌ ffmpeg required for adaptive streaming downloads.[/red]\n"
                "Install: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
            )
            await client.aclose()
            raise typer.Exit(1)
        try:
            await download_manifest(target.download_url, output_path, cookies)
            if not quiet:
                console.print(f"\n[green]✅ Downloaded:[/green] {output_path}")
        except SpDlError as e:
            err_console.print(f"[red]❌ Download Error:[/red] {e}")
            raise typer.Exit(1) from None
    else:
        if not quiet:
            console.print("[bold]📥 Downloading...[/bold]")

        rate = parse_rate_limit(limit_rate or config.limit_rate or None)

        progress = create_download_progress()
        task_id = progress.add_task(
            "download",
            total=meta.size_bytes or None,
            filename=meta.name,
        )

        def progress_cb(bytes_written: int):
            progress.update(task_id, advance=bytes_written)

        try:
            with progress:
                result = await download_file(
                    client=client,
                    target=target,
                    output_path=output_path,
                    progress_callback=progress_cb,
                    limit_rate=rate,
                    no_overwrites=no_overwrites,
                )

            if not quiet:
                console.print()
                if result.bytes_downloaded > 0:
                    speed = result.bytes_downloaded / max(result.elapsed_seconds, 0.01)
                    console.print(
                        f"[green]✅ Downloaded:[/green] {result.output_path} "
                        f"({format_size(result.bytes_downloaded)}, "
                        f"{format_size(int(speed))}/s)"
                    )
                else:
                    console.print(f"[yellow]⏭️  Skipped:[/yellow] {output_path} (already exists)")

        except SpDlError as e:
            # If download fails with 401/403 on a stream video, try media stream
            if parsed.url_type == URLType.STREAM_ASPX and "access denied" in str(e).lower():
                if not quiet:
                    err_console.print(
                        "\n[yellow]⚠ Download blocked — "
                        "switching to OAuth2 video streaming...[/yellow]"
                    )
                    console.print()
                target = await _resolve_via_media_stream(parsed, client, effective_tenant, quiet)
                # Retry as manifest download
                meta = target.metadata
                if not is_ffmpeg_available():
                    err_console.print(
                        "[red]❌ ffmpeg required for streaming downloads.[/red]\n"
                        "Install: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
                    )
                    await client.aclose()
                    raise typer.Exit(1) from None
                try:
                    await download_manifest(target.download_url, output_path, cookies)
                    if not quiet:
                        console.print(f"\n[green]✅ Downloaded:[/green] {output_path}")
                except SpDlError as me:
                    err_console.print(f"[red]❌ Stream Download Error:[/red] {me}")
                    raise typer.Exit(1) from None
            else:
                err_console.print(f"\n[red]❌ Download Error:[/red] {e}")
                raise typer.Exit(1) from None

    await client.aclose()


async def _resolve_via_media_stream(
    parsed,
    client,
    tenant: str | None,
    quiet: bool,
):
    """Resolve a download-blocked video via OAuth2 + media proxy DASH streaming."""
    from sp_dl.auth.device_code import DeviceCodeAuthProvider
    from sp_dl.auth.token_cache import TokenCache
    from sp_dl.constants import OFFICE_CLIENT_ID
    from sp_dl.models import SpDlError
    from sp_dl.resolver.media_stream import MediaStreamResolver

    effective_tenant = tenant or "common"
    tenant_domain = parsed.tenant_domain
    scopes = [f"https://{tenant_domain}/.default", "offline_access"]

    # Acquire OAuth2 token via device code flow (with cache)
    cache = TokenCache(cache_dir=TokenCache()._cache_dir / f"media_{tenant_domain}")
    auth = DeviceCodeAuthProvider(
        tenant=effective_tenant,
        client_id=OFFICE_CLIENT_ID,
        scopes=scopes,
        token_cache=cache,
    )

    try:
        import httpx as _httpx

        temp_client = _httpx.AsyncClient(timeout=30, follow_redirects=True)
        await auth.authenticate(temp_client)
        await temp_client.aclose()
    except SpDlError as e:
        err_console.print(f"[red]❌ OAuth2 Error:[/red] {e}")
        await client.aclose()
        raise typer.Exit(1) from None

    oauth_token = auth._access_token
    if not oauth_token:
        err_console.print("[red]❌ Failed to obtain OAuth2 token[/red]")
        await client.aclose()
        raise typer.Exit(1) from None

    if not quiet:
        console.print("   [green]✓[/green] OAuth2 token acquired")
        console.print()

    # Resolve via media stream
    resolver = MediaStreamResolver(oauth_token=oauth_token)
    try:
        target = await resolver.resolve(parsed, client)
    except SpDlError as e:
        err_console.print(f"[red]❌ Media Stream Error:[/red] {e}")
        await client.aclose()
        raise typer.Exit(1) from None

    return target


async def _auth_login_async(tenant: str, client_id: str | None, interactive: bool):
    """Execute auth login flow."""
    import httpx

    from sp_dl.auth.device_code import DeviceCodeAuthProvider
    from sp_dl.auth.interactive import InteractiveAuthProvider
    from sp_dl.constants import DEFAULT_CLIENT_ID

    base_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    try:
        if interactive:
            provider = InteractiveAuthProvider(
                tenant=tenant,
                client_id=client_id or DEFAULT_CLIENT_ID,
            )
        else:
            provider = DeviceCodeAuthProvider(
                tenant=tenant,
                client_id=client_id or DEFAULT_CLIENT_ID,
            )

        await provider.authenticate(base_client)
    except Exception as e:
        err_msg = str(e)
        err_console.print(f"[red]❌ Login failed:[/red] {e}")

        # Give specific guidance for common Azure AD errors
        if "AADSTS700016" in err_msg:
            err_console.print()
            err_console.print(
                "[yellow]This means the Azure CLI public client ID is not allowed "
                "in your organization.[/yellow]"
            )
            err_console.print("Options:")
            err_console.print(
                "  1. [bold]Use cookies instead (easiest):[/bold] "
                "sp-dl download URL --cookies cookies.txt"
            )
            err_console.print("  2. Register your own Azure AD app and pass --client-id")
            err_console.print(
                "     See: https://github.com/sp-dl/sp-dl/blob/main/docs/auth-setup.md"
            )
        elif "AADSTS50059" in err_msg or "No tenant-identifying" in err_msg:
            err_console.print()
            err_console.print("[yellow]Tenant not found. Make sure to pass your tenant:[/yellow]")
            err_console.print("  sp-dl auth login --tenant YOUR_ORG.onmicrosoft.com")
            err_console.print("  sp-dl auth login --tenant https://YOUR_ORG.sharepoint.com")
        elif "invalid_request" in err_msg:
            err_console.print()
            err_console.print("[yellow]Tip:[/yellow] Cookie auth is easier and works everywhere:")
            err_console.print("  sp-dl download URL --cookies cookies.txt")

        raise typer.Exit(1) from None
    finally:
        await base_client.aclose()


# ─── Utilities ────────────────────────────────────────────────────────────────


def _normalize_tenant(tenant: str) -> str:
    """Normalize tenant input to Azure AD tenant identifier.

    Accepts:
      - "contoso.onmicrosoft.com" -> "contoso.onmicrosoft.com"
      - "contoso" -> "contoso.onmicrosoft.com"
      - "https://contoso.sharepoint.com" -> "contoso.onmicrosoft.com"
      - "https://contoso-my.sharepoint.com/..." -> "contoso.onmicrosoft.com"
      - "contoso.sharepoint.com" -> "contoso.onmicrosoft.com"
    """
    tenant = tenant.strip().rstrip("/")

    # Handle full URLs
    if "sharepoint.com" in tenant:
        # Extract the tenant name from the SharePoint domain
        import re

        m = re.search(r"([\w-]+?)(?:-my)?\.sharepoint\.com", tenant)
        if m:
            return f"{m.group(1)}.onmicrosoft.com"

    # Already fully qualified
    if ".onmicrosoft.com" in tenant or "." in tenant:
        return tenant

    # Short name: "contoso" -> "contoso.onmicrosoft.com"
    return f"{tenant}.onmicrosoft.com"


def _setup_logging(verbose: bool, debug: bool, quiet: bool):
    """Configure logging based on CLI flags."""
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    elif quiet:
        level = logging.ERROR
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    app()
