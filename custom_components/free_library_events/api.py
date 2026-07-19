"""Async client for official Free Library branch RSS feeds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import date

import aiohttp

from .digest import Branch, Event, event_identity, merge_events, parse_feed

RSS_ITEM_LIMIT = 10
MAX_RSS_RESPONSE_BYTES = 256 * 1024
MAX_RSS_REQUEST_CONCURRENCY = 8
OFFICIAL_EVENT_TYPES = (
    "Arts and Crafts Programs",
    "Author Events",
    "Black History Month",
    "Business",
    "Career Workshops",
    "Community Events",
    "Computer Classes",
    "Discussion and Participation",
    "Exhibitions",
    "Family Programs",
    "Film Screening",
    "Health Programs",
    "LEAP",
    "Live Performances",
    "New Americans",
    "One Book Author and Featured Events",
    "Other Great Programs",
    "Speakers and Lectures",
    "Workshops and Enrichment",
)


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
    type_shards_queried: int = 0
    type_shard_failures: tuple[str, ...] = ()
    expanded_through: date | None = None

    def covers_through(self, end_date: date) -> bool:
        """Return whether feed evidence proves coverage through a date."""

        if self.expanded_through is not None and self.expanded_through >= end_date:
            return True
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
        self._request_semaphore = asyncio.Semaphore(MAX_RSS_REQUEST_CONCURRENCY)

    async def _async_get(self, url: str) -> bytes:
        async with self._session.get(
            url,
            headers={"User-Agent": "HomeAssistant Free Library Events"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            try:
                await response.content.readexactly(MAX_RSS_RESPONSE_BYTES + 1)
            except asyncio.IncompleteReadError as err:
                return err.partial
            raise LibraryApiError(
                f"RSS response exceeded {MAX_RSS_RESPONSE_BYTES} bytes"
            )

    async def async_fetch_feed(
        self,
        branch: Branch,
        age_category: str,
    ) -> BranchFeed:
        """Fetch one official branch-and-age feed."""

        return await self._async_fetch_single(branch, age_category)

    async def async_expand_feed(
        self,
        branch: Branch,
        age_category: str,
        base_feed: BranchFeed,
        coverage_end: date,
    ) -> BranchFeed:
        """Expand one unresolved capped feed across official event types."""

        results = await asyncio.gather(
            *(
                self._async_fetch_type_shard(branch, age_category, event_type)
                for event_type in OFFICIAL_EVENT_TYPES
            ),
            return_exceptions=True,
        )
        events = list(base_feed.events)
        successful_shards: list[BranchFeed] = []
        failures: list[str] = []
        for event_type, result in zip(OFFICIAL_EVENT_TYPES, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                failures.append(f"{event_type}: {result}")
                continue
            if not isinstance(result, BranchFeed):
                failures.append(f"{event_type}: unexpected response")
                continue
            successful_shards.append(result)
            events.extend(result.events)

        merged_events = merge_events(events)
        base_ids = {event_identity(event) for event in base_feed.events}
        shard_ids = {
            event_identity(event) for feed in successful_shards for event in feed.events
        }
        expansion_proves_coverage = (
            not failures
            and len(successful_shards) == len(OFFICIAL_EVENT_TYPES)
            and base_ids <= shard_ids
            and all(feed.covers_through(coverage_end) for feed in successful_shards)
        )
        return replace(
            base_feed,
            events=tuple(merged_events),
            type_shards_queried=len(OFFICIAL_EVENT_TYPES),
            type_shard_failures=tuple(failures),
            expanded_through=coverage_end if expansion_proves_coverage else None,
        )

    async def _async_fetch_type_shard(
        self,
        branch: Branch,
        age_category: str,
        event_type: str,
    ) -> BranchFeed:
        """Fetch one official publisher event-type shard."""

        return await self._async_fetch_single(branch, age_category, event_type)

    async def _async_fetch_single(
        self,
        branch: Branch,
        age_category: str,
        event_type: str | None = None,
    ) -> BranchFeed:
        """Fetch and parse one official RSS query."""

        url = (
            branch.rss_url_for_age_and_type(age_category, event_type)
            if event_type
            else branch.rss_url_for_age(age_category)
        )
        source_name = f"{branch.name} {age_category}"
        if event_type:
            source_name += f" {event_type}"

        try:
            async with self._request_semaphore:
                payload = await self._async_get(url)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise LibraryApiError(f"Unable to load {source_name} feed") from err

        try:
            events, source_count = await asyncio.to_thread(
                parse_feed,
                payload,
                branch,
                age_category,
            )
        except (ValueError, TypeError) as err:
            raise LibraryApiError(
                f"Invalid event data from {source_name} feed"
            ) from err
        except Exception as err:
            raise LibraryApiError(f"Unable to parse {source_name} feed") from err

        event_dates = [event.event_date for event in events]
        return BranchFeed(
            events=tuple(events),
            age_category=age_category,
            source_count=source_count,
            parsed_count=len(events),
            last_event_date=event_dates[-1] if event_dates else None,
            ordered=event_dates == sorted(event_dates),
        )
