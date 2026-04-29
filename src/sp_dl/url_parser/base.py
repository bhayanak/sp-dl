"""Base URL parser interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sp_dl.models import ParsedURL


class URLParser(ABC):
    """Abstract base class for SharePoint URL parsers."""

    @abstractmethod
    def can_parse(self, url: str) -> bool:
        """Check if this parser can handle the given URL."""

    @abstractmethod
    def parse(self, url: str) -> ParsedURL:
        """Parse the URL and return a ParsedURL dataclass."""
