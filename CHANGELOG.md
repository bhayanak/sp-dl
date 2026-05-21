# Changelog

All notable changes to sharepoint-dl will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.1.0] - 2026-05-21

### Added

- **Parallel DASH downloader** — downloads adaptive stream segments concurrently (10 connections) instead of sequentially through ffmpeg; ffmpeg is now only used for final audio+video muxing
- **Media stream resolver** — automatically resolves download-blocked videos via Microsoft's media proxy DASH endpoint with OAuth2 authentication
- **Domain-specific token caching** — media stream tokens are cached per SharePoint domain (`~/.config/sp-dl/media_{domain}/token.json`) to prevent scope conflicts with Graph API tokens
- **REST API fallback** for extracting drive/item IDs when stream page HTML is unavailable
- **Pre-signed manifest URL extraction** — attempts to extract embedded manifest URLs from `g_fileInfo` before falling back to OAuth2

### Fixed

- **OAuth2 token scope mismatch** — previously, a cached Graph-scoped token could be incorrectly used for SharePoint media proxy requests, causing 401 errors
- **Cookie Monster rtFa** — fixed parent-domain cookie (`.sharepoint.com`) handling so `rtFa` is correctly sent alongside `FedAuth`
- **Download-blocked detection** — improved fallback logic when direct download returns 401/403 on enterprise tenants with admin download restrictions

### Removed

- **Auto-extract from browser** (`--auto-extract` / `-a` option) — removed `browser-cookie3` dependency; use `--cookies` with an exported cookie file instead
- `browser-cookie3` from dependencies

### Changed

- Download-blocked videos now use parallel segment downloads (significantly faster) instead of piping through ffmpeg
- Token cache architecture: media stream tokens are isolated from `sp-dl auth login` tokens to prevent audience conflicts

## [0.1.0] - 2026-04-29

### Added

- Initial release
- Download files from SharePoint document libraries
- Support for 5 URL patterns: stream.aspx, sharing links, direct paths, OneDrive, Doc.aspx
- Cookie-based authentication (Netscape format file)
- Auto-extract cookies from Chrome, Edge, Firefox
- OAuth2 Device Code flow for headless/CI usage
- Interactive browser-based OAuth2 login
- Client Credentials flow for service accounts
- Chunked streaming downloads (never buffers entire file in memory)
- Resume interrupted downloads via HTTP Range headers
- Rich terminal progress bar with speed and ETA
- Output path templates (%(filename)s, %(site)s, etc.)
- File info mode (--info, --json) without downloading
- Batch download from URL list file
- Rate limiting (--limit-rate)
- Skip existing files (--no-overwrites)
- Automatic retry with exponential backoff
- SharePoint throttling detection (HTTP 429 + Retry-After)
- Config file support (~/.config/sp-dl/config.toml)
- Environment variable configuration
- Token caching with restricted file permissions
- Auth management commands: login, status, logout
- ffmpeg fallback for adaptive streaming (DASH/HLS)
- CI/CD with GitHub Actions (Python 3.10-3.13)
- PyPI publishing workflow
