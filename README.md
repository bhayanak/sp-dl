# sp-dl

**Download videos and files from SharePoint — like yt-dlp for SharePoint.**

[![CI](https://github.com/bhayanak/sp-dl/actions/workflows/ci.yml/badge.svg)](https://github.com/bhayanak/sp-dl/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/sp-dl)](https://pypi.org/project/sp-dl/)
[![Python](https://img.shields.io/pypi/pyversions/sp-dl)](https://pypi.org/project/sp-dl/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## Why?

- Microsoft Stream (Classic) was retired — all videos now live in **SharePoint / OneDrive**
- Browser downloads fail for large files, offer no resume, and require clicking through menus
- **yt-dlp** doesn't support SharePoint authentication
- `sp-dl` gives you **one command** to download any file from SharePoint

## What It Downloads

| Content | Source |
|---|---|
| Videos (.mp4, .mov, .webm) | SharePoint document libraries, Stream on SharePoint |
| Meeting recordings | OneDrive / SharePoint auto-saved recordings |
| Any file | SharePoint document libraries |
| Shared links | Anonymous or org-internal sharing links |

## Install

```bash
pip install sp-dl
```

Or with [pipx](https://pipx.pypa.io/) for isolated install:

```bash
pipx install sp-dl
```

## Quick Start

**First time?** Run `sp-dl quickstart` for a step-by-step guide.

### Using Cookies (Recommended — Easiest)

1. Log into SharePoint in your browser
2. Export cookies to a file using a browser extension like **"Get cookies.txt LOCALLY"**
3. Download:

```bash
sp-dl download "https://contoso.sharepoint.com/sites/Team/_layouts/15/stream.aspx?id=/sites/Team/Shared%20Documents/demo.mp4" \
  --cookies cookies.txt
```

### Auto-Extract Cookies from Browser

```bash
pip install 'sp-dl[browser-cookies]'

# Close your browser first, then:
sp-dl download "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/demo.mp4" \
  --cookies-from-browser chrome
```

### Using Device Code (OAuth — for enterprise tenants)

```bash
# One-time login (you'll be prompted for your org tenant)
sp-dl auth login --tenant contoso

# Download (uses saved token)
sp-dl download "https://contoso.sharepoint.com/sites/Team/Shared%20Documents/video.mp4"
```

> **Note:** OAuth login requires your Azure AD tenant to allow the Azure CLI public client.
> If you get an error about the app not being found, use the cookie method instead.

## Usage

```bash
# Download a video
sp-dl download <URL> --cookies cookies.txt

# Download from a sharing link
sp-dl download "https://contoso.sharepoint.com/:v:/s/Team/EaBcDeFgHiJk" -c cookies.txt

# Auto-extract cookies from browser
sp-dl download <URL> --cookies-from-browser chrome

# Show file info without downloading
sp-dl download <URL> --info -c cookies.txt

# JSON metadata
sp-dl download <URL> --json -c cookies.txt

# Custom output path
sp-dl download <URL> -o ~/Videos/meeting.mp4 -c cookies.txt

# Output template
sp-dl download <URL> -o "%(site)s/%(folder)s/%(filename)s" -c cookies.txt

# Limit speed
sp-dl download <URL> --limit-rate 5M -c cookies.txt

# Skip existing files
sp-dl download <URL> --no-overwrites -c cookies.txt

# Batch download (one URL per line)
sp-dl batch urls.txt -c cookies.txt

# Quick start guide
sp-dl quickstart
```

## Supported URL Patterns

| Pattern | Example |
|---|---|
| Stream player | `https://tenant.sharepoint.com/sites/Team/_layouts/15/stream.aspx?id=...` |
| Sharing link | `https://tenant.sharepoint.com/:v:/s/Team/EncodedToken` |
| Direct path | `https://tenant.sharepoint.com/sites/Team/Shared%20Documents/file.mp4` |
| OneDrive | `https://tenant-my.sharepoint.com/personal/user/Documents/file.mp4` |
| Doc.aspx | `https://tenant.sharepoint.com/sites/Team/_layouts/15/Doc.aspx?sourcedoc={guid}` |

## Authentication Methods

| Method | Best For | Setup |
|---|---|---|
| `--cookies` | Quick downloads, read-only users | Export cookies from browser |
| `--cookies-from-browser` | Desktop users | Auto-extract from Chrome/Edge/Firefox |
| `sp-dl auth login` | Headless servers, CI/CD | One-time Azure AD app registration |
| `--client-id --client-secret` | Service accounts | Azure AD admin setup |

## Auth Management

```bash
sp-dl auth login --tenant contoso       # Device code login (prompted for tenant)
sp-dl auth login --tenant contoso -i    # Browser-based login
sp-dl auth status                        # Check auth state
sp-dl auth logout                        # Clear tokens
```

> **Tip:** You can pass a SharePoint URL as the tenant and it will be auto-detected:
> `sp-dl auth login --tenant https://contoso.sharepoint.com`

## Output Templates

| Field | Description | Example |
|---|---|---|
| `%(filename)s` | Original filename | `training.mp4` |
| `%(title)s` | Name without extension | `training` |
| `%(ext)s` | Extension | `mp4` |
| `%(site)s` | SharePoint site | `Team` |
| `%(folder)s` | Parent folder | `Recordings` |
| `%(date)s` | Modified date | `20260415` |
| `%(author)s` | Created by | `John Smith` |

## Configuration

Create `~/.config/sp-dl/config.toml`:

```toml
[defaults]
output_template = "%(filename)s"
cookies_file = "/path/to/cookies.txt"
retries = 5
no_overwrites = false

[auth]
tenant = "contoso.onmicrosoft.com"
```

Environment variables: `SP_DL_COOKIES`, `SP_DL_TENANT`, `SP_DL_CLIENT_ID`, `SP_DL_OUTPUT`

## Development

```bash
git clone https://github.com/sp-dl/sp-dl.git
cd sp-dl
pip install -e ".[dev]"

# Run tests
pytest -v

# Lint & format
ruff check src/ tests/
ruff format src/ tests/
```

## License

[MIT](LICENSE)
