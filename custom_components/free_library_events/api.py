"""Async client for official Free Library branch RSS feeds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp

from .digest import Branch, Event, parse_feed


class LibraryApiError(Exception):
    """Raised when a branch feed cannot be loaded or parsed."""


@dataclass(frozen=True, slots=True)
class BranchFeed:
    """Normalized result from one branch feed."""

    events: tuple[Event, ...]
    source_count: int


class LibraryClient:
    """Fetch Free Library events using Home Assistant's shared HTTP session."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def async_fetch_branch(self, branch: Branch) -> BranchFeed:
        """Fetch and parse one official RSS feed."""

        try:
            async with self._session.get(
                branch.rss_url,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                response.raise_for_status()
                payload = await response.read()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise LibraryApiError(f"Unable to load {branch.name}") from err

        try:
            events, source_count = await asyncio.to_thread(parse_feed, payload, branch)
        except (ValueError, TypeError) as err:
            raise LibraryApiError(f"Invalid event data from {branch.name}") from err
        except Exception as err:
            raise LibraryApiError(f"Unable to parse {branch.name}") from err

        return BranchFeed(tuple(events), source_count)
