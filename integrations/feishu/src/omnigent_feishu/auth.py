"""Bearer acquisition seams for authenticated Omnigent HTTP calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol


class BearerProvider(Protocol):
    async def token(self) -> str: ...
    async def refresh(self) -> str: ...


class StaticBearerProvider:
    """Service/delegated bearer supplied by the integration operator."""

    def __init__(self, bearer: str) -> None:
        if not bearer:
            raise ValueError("Omnigent bearer is required")
        self._bearer = bearer

    async def token(self) -> str:
        return self._bearer

    async def refresh(self) -> str:
        return self._bearer


class RefreshingBearerProvider:
    """Small adapter around async load and refresh callbacks."""

    def __init__(
        self,
        load: Callable[[], Awaitable[str]],
        rotate: Callable[[], Awaitable[str]],
    ) -> None:
        self._load = load
        self._rotate = rotate

    async def token(self) -> str:
        return await self._load()

    async def refresh(self) -> str:
        return await self._rotate()


__all__ = ["BearerProvider", "RefreshingBearerProvider", "StaticBearerProvider"]
