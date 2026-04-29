"""Base resolver interface and orchestration."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from sp_dl.models import (
    AccessDeniedError,
    DownloadBlockedError,
    DownloadTarget,
    FileNotFoundOnServerError,
    ParsedURL,
    ResolveError,
    URLType,
)

logger = logging.getLogger(__name__)


class Resolver(ABC):
    """Abstract base class for URL resolvers."""

    @abstractmethod
    async def resolve(self, parsed: ParsedURL, client: httpx.AsyncClient) -> DownloadTarget:
        """Resolve a parsed URL to a downloadable target."""

    @abstractmethod
    def can_handle(self, parsed: ParsedURL) -> bool:
        """Check if this resolver can handle the given URL type."""


async def resolve_download_target(
    parsed: ParsedURL,
    client: httpx.AsyncClient,
) -> DownloadTarget:
    """
    Try resolution strategies in order, falling back on failure.

    Strategy order:
    1. SharePoint REST API (best for cookie auth, direct paths)
    2. Graph API (best for OAuth, sharing links)
    3. Stream page extraction (fallback for stream.aspx)
    4. Sharing link decoder (for sharing URLs)
    """
    from sp_dl.resolver.graph_api import GraphAPIResolver
    from sp_dl.resolver.sharing import SharingLinkResolver
    from sp_dl.resolver.sp_rest import SharePointRESTResolver
    from sp_dl.resolver.stream_page import StreamPageResolver

    # Build resolver list based on URL type
    resolvers: list[Resolver] = []

    if parsed.url_type == URLType.SHARING_LINK:
        resolvers = [SharingLinkResolver(), GraphAPIResolver()]
    elif parsed.url_type == URLType.STREAM_ASPX:
        resolvers = [
            StreamPageResolver(),
            SharePointRESTResolver(),
            GraphAPIResolver(),
        ]
    elif parsed.url_type == URLType.DOC_ASPX:
        resolvers = [GraphAPIResolver(), SharePointRESTResolver()]
    else:
        resolvers = [
            SharePointRESTResolver(),
            GraphAPIResolver(),
            StreamPageResolver(),
        ]

    errors: list[str] = []
    for resolver in resolvers:
        if not resolver.can_handle(parsed):
            continue
        try:
            logger.debug(f"Trying resolver: {resolver.__class__.__name__}")
            target = await resolver.resolve(parsed, client)
            logger.info(f"Resolved via {resolver.__class__.__name__}")
            return target
        except DownloadBlockedError:
            # Let this propagate — caller must handle OAuth2 flow
            raise
        except AccessDeniedError as e:
            errors.append(f"{resolver.__class__.__name__}: Access denied - {e}")
            continue
        except (ResolveError, FileNotFoundOnServerError, httpx.HTTPError) as e:
            errors.append(f"{resolver.__class__.__name__}: {e}")
            continue

    error_details = "\n  ".join(errors) if errors else "No suitable resolver found"
    raise ResolveError(
        f"All resolution strategies failed for: {parsed.original_url}\n  {error_details}"
    )
