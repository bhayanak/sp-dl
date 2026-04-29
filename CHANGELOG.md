# Changelog

All notable changes to sp-dl will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

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
