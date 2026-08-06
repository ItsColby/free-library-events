"""Async client for official Free Library branch RSS feeds."""

from __future__ import annotations

import asyncio
import urllib.parse
from dataclasses import dataclass, replace
from datetime import date

import aiohttp

from .digest import Branch, Event, event_identity, merge_events, parse_feed

RSS_ITEM_LIMIT = 10
MAX_RSS_RESPONSE_BYTES = 256 * 1024
MAX_RSS_REQUEST_CONCURRENCY = 8
MAX_RSS_REDIRECTS = 2
TRUSTED_RSS_HOSTS = frozenset({"libwww.freelibrary.org", "www.freelibrary.org"})
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

SOURCE_ERROR_REQUEST_FAILED = "request_failed"
SOURCE_ERROR_INVALID_FEED = "invalid_feed"
SOURCE_ERROR_PARSE_FAILED = "parse_failed"
SOURCE_ERROR_RESPONSE_TOO_LARGE = "response_too_large"
SOURCE_ERROR_UNSAFE_REDIRECT = "unsafe_redirect"
SOURCE_ERROR_EXPANSION_TIMEOUT = "expansion_timeout"
SOURCE_ERROR_UNEXPECTED = "unexpected_failure"
SOURCE_ERROR_CATEGORIES = frozenset(
    {
        SOURCE_ERROR_REQUEST_FAILED,
        SOURCE_ERROR_INVALID_FEED,
        SOURCE_ERROR_PARSE_FAILED,
        SOURCE_ERROR_RESPONSE_TOO_LARGE,
        SOURCE_ERROR_UNSAFE_REDIRECT,
        SOURCE_ERROR_EXPANSION_TIMEOUT,
        SOURCE_ERROR_UNEXPECTED,
    }
)

SOURCE_ERROR_DESCRIPTIONS = {
    SOURCE_ERROR_REQUEST_FAILED: "library source request failed",
    SOURCE_ERROR_INVALID_FEED: "library source returned invalid event data",
    SOURCE_ERROR_PARSE_FAILED: "library source could not be parsed",
    SOURCE_ERROR_RESPONSE_TOO_LARGE: "library source response exceeded its size limit",
    SOURCE_ERROR_UNSAFE_REDIRECT: "library source used an unsafe redirect",
    SOURCE_ERROR_EXPANSION_TIMEOUT: "library source expansion timed out",
    SOURCE_ERROR_UNEXPECTED: "unexpected source failure",
}


class LibraryApiError(Exception):
    """Raised when a branch feed cannot be loaded or parsed."""

    def __init__(self, category: str) -> None:
        safe_category = (
            category if category in SOURCE_ERROR_CATEGORIES else SOURCE_ERROR_UNEXPECTED
        )
        super().__init__(safe_category)
        self.category = safe_category


def source_error_category(error: BaseException) -> str:
    """Return an allow-listed category without retaining exception text."""

    if isinstance(error, LibraryApiError):
        return error.category
    return SOURCE_ERROR_UNEXPECTED


def source_error_description(category: str) -> str:
    """Return a bounded public-safe description for a source error category."""

    return SOURCE_ERROR_DESCRIPTIONS.get(
        category,
        SOURCE_ERROR_DESCRIPTIONS[SOURCE_ERROR_UNEXPECTED],
    )


def _is_trusted_rss_url(url: str) -> bool:
    """Return whether a source URL stays on the publisher's HTTPS boundary."""

    try:
        parsed = urllib.parse.urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").casefold() in TRUSTED_RSS_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
    )


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
        current_url = url
        for redirect_count in range(MAX_RSS_REDIRECTS + 1):
            if not _is_trusted_rss_url(current_url):
                raise LibraryApiError(SOURCE_ERROR_UNSAFE_REDIRECT)
            async with self._session.get(
                current_url,
                allow_redirects=False,
                headers={"User-Agent": "HomeAssistant Free Library Events"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if 300 <= response.status < 400:
                    location = response.headers.get("Location", "")
                    if not location or redirect_count == MAX_RSS_REDIRECTS:
                        raise LibraryApiError(SOURCE_ERROR_UNSAFE_REDIRECT)
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                response.raise_for_status()
                try:
                    await response.content.readexactly(MAX_RSS_RESPONSE_BYTES + 1)
                except asyncio.IncompleteReadError as err:
                    return err.partial
                raise LibraryApiError(SOURCE_ERROR_RESPONSE_TOO_LARGE)
        raise LibraryApiError(SOURCE_ERROR_UNSAFE_REDIRECT)

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
                failures.append(f"{event_type}: {source_error_category(result)}")
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
        try:
            async with self._request_semaphore:
                payload = await self._async_get(url)
        except (TimeoutError, aiohttp.ClientError) as err:
            raise LibraryApiError(SOURCE_ERROR_REQUEST_FAILED) from err

        try:
            events, source_count = await asyncio.to_thread(
                parse_feed,
                payload,
                branch,
                age_category,
            )
        except (ValueError, TypeError) as err:
            raise LibraryApiError(SOURCE_ERROR_INVALID_FEED) from err
        except Exception as err:
            raise LibraryApiError(SOURCE_ERROR_PARSE_FAILED) from err

        event_dates = [event.event_date for event in events]
        return BranchFeed(
            events=tuple(events),
            age_category=age_category,
            source_count=source_count,
            parsed_count=len(events),
            last_event_date=event_dates[-1] if event_dates else None,
            ordered=event_dates == sorted(event_dates),
        )
