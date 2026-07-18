"""Async client for official Free Library branch RSS feeds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

import aiohttp

from .digest import Branch, Event, parse_feed

RSS_ITEM_LIMIT = 10


class LibraryApiError(Exception):
    """Raised when a branch feed cannot be loaded or parsed."""


@dataclass(frozen=True, slots=True)
class BranchFeed:
    """Normalized result and coverage evidence from one custom feed."""

    events: tuple[Event, ...]
    age_category: str
    source_count: int
    parsed_count: int
    last_event_date: date | None
    ordered: bool

    def covers_through(self, end_date: date) -> bool:
        """Return whether feed evidence proves coverage through a date."""

        if self.parsed_count != self.source_count:
            return False
        if self.source_count < RSS_ITEM_LIMIT:
            return True
        return bool(
            self.ordered
            and self.last_event_date is not None
            and self.last_event_date > end_date
        )


class LibraryClient:
    """Fetch Free Library events using Home Assistant's shared HTTP session."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _async_get(self, url: str) -> bytes:
        async with self._session.get(
            url,
            headers={"User-Agent": "HomeAssistant Free Library Events"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            return await response.read()

    async def async_fetch_feed(
        self,
        branch: Branch,
        age_category: str,
    ) -> BranchFeed:
        """Fetch one official branch-plus-age custom RSS feed."""

        try:
            payload = await self._async_get(branch.rss_url_for_age(age_category))
        except (TimeoutError, aiohttp.ClientError) as err:
            raise LibraryApiError(
                f"Unable to load {branch.name} {age_category} feed"
            ) from err

        try:
            events, source_count = await asyncio.to_thread(
                parse_feed,
                payload,
                branch,
                age_category,
            )
        except (ValueError, TypeError) as err:
            raise LibraryApiError(
                f"Invalid event data from {branch.name} {age_category} feed"
            ) from err
        except Exception as err:
            raise LibraryApiError(
                f"Unable to parse {branch.name} {age_category} feed"
            ) from err

        event_dates = [event.event_date for event in events]
        return BranchFeed(
            events=tuple(events),
            age_category=age_category,
            source_count=source_count,
            parsed_count=len(events),
            last_event_date=event_dates[-1] if event_dates else None,
            ordered=event_dates == sorted(event_dates),
        )
