"""Base auth provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from sp_dl.models import AuthMethod


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    @property
    @abstractmethod
    def method(self) -> AuthMethod:
        """Return the auth method type."""

    @abstractmethod
    async def authenticate(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        """
        Apply authentication to the HTTP client.

        Returns a client with auth headers/cookies configured.
        """

    @abstractmethod
    async def is_valid(self, client: httpx.AsyncClient) -> bool:
        """Check if the current auth credentials are still valid."""

    async def refresh(self, client: httpx.AsyncClient) -> httpx.AsyncClient:
        """Refresh expired credentials. Default: re-authenticate."""
        return await self.authenticate(client)

    @property
    def description(self) -> str:
        """Human-readable description of the auth state."""
        return f"{self.method.value} authentication"
