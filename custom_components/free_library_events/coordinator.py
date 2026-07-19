"""Data coordinator for Free Library Events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import logging
from typing import Sequence

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OFFICIAL_EVENT_TYPES, RSS_ITEM_LIMIT, BranchFeed, LibraryClient
from .const import DOMAIN
from .digest import (
    AGE_CATEGORY_ORDER,
    AGE_CATEGORY_WINDOWS,
    BRANCHES,
    Branch,
    Event,
    age_in_months,
    age_categories_for_window,
    merge_events,
    next_week_start,
    source_age_categories_for_window,
)

_LOGGER = logging.getLogger(__name__)
SOURCE_AGE_HORIZON = timedelta(days=90)
MAX_TYPE_EXPANSIONS_PER_REFRESH = 12
MAX_TYPE_FAILURE_EXAMPLES = 3


def source_key(branch: Branch, age_category: str) -> str:
    """Return a stable key for one branch feed."""

    return f"{branch.code}:{age_category}"


def source_label(key: str) -> str:
    """Return a human-readable label for a source key."""

    branch_code, source = key.split(":", 1)
    return f"{BRANCHES[branch_code].name} — {source}"


def source_keys_for_window(
    keys: Sequence[str],
    birth_date: date,
    start_date: date,
    end_date: date,
) -> list[str]:
    """Return source keys relevant to the child's age in a target window."""

    categories = set(age_categories_for_window(birth_date, start_date, end_date))
    return [key for key in keys if key.split(":", 1)[1] in categories]


def supplemental_source_keys(
    keys: Sequence[str],
    birth_date: date,
    start_date: date,
    end_date: date,
) -> list[str]:
    """Return source keys used for inclusive discovery beyond the current age."""

    relevant = set(age_categories_for_window(birth_date, start_date, end_date))
    return [key for key in keys if key.split(":", 1)[1] not in relevant]


def source_expansion_details(data: LibraryData) -> dict[str, dict[str, object]]:
    """Return compact diagnostics for adaptively expanded capped sources."""

    return {
        source_label(key): {
            "discovered_event_count": len(feed.events),
            "type_feeds_queried": feed.type_shards_queried,
            "type_feed_failure_count": len(feed.type_shard_failures),
            "type_feed_failure_examples": list(
                feed.type_shard_failures[:MAX_TYPE_FAILURE_EXAMPLES]
            ),
            "coverage_through": feed.expanded_through.isoformat()
            if feed.expanded_through
            else None,
        }
        for key, feed in data.source_statuses.items()
        if feed.type_shards_queried
    }


def type_expansion_source_keys(
    statuses: dict[str, BranchFeed],
    birth_date: date,
    today: date,
    coverage_end: date,
) -> tuple[str, ...]:
    """Select capped sources while covering current ages before nearby windows."""

    current_categories = set(
        age_categories_for_window(
            birth_date,
            next_week_start(today),
            coverage_end,
        )
    )
    child_months = age_in_months(birth_date, next_week_start(today))
    age_window_by_category = {
        category: (minimum, maximum)
        for category, minimum, maximum in AGE_CATEGORY_WINDOWS
    }

    def expansion_priority(key: str) -> tuple[bool, float, int, str]:
        branch_code, category = key.split(":", 1)
        minimum, maximum = age_window_by_category[category]
        distance = max(minimum - child_months, child_months - maximum, 0)
        return (
            category not in current_categories,
            distance,
            AGE_CATEGORY_ORDER[category],
            branch_code,
        )

    return tuple(
        sorted(
            (
                key
                for key, feed in statuses.items()
                if feed.type_shards_queried == 0
                and feed.source_count == RSS_ITEM_LIMIT
                and feed.parsed_count == feed.source_count
                and feed.ordered
                and not feed.covers_through(coverage_end)
            ),
            key=expansion_priority,
        )[:MAX_TYPE_EXPANSIONS_PER_REFRESH]
    )


@dataclass(frozen=True, slots=True)
class LibraryData:
    """Latest normalized events and branch-source health."""

    events: tuple[Event, ...]
    source_counts: dict[str, int]
    source_statuses: dict[str, BranchFeed]
    source_errors: dict[str, str]
    fetched_at: datetime


def coverage_warnings(
    data: LibraryData,
    birth_date: date,
    start_date: date,
    end_date: date,
) -> list[str]:
    """Return unresolved feed-coverage warnings through a target date."""

    warnings: list[str] = []
    relevant_keys = source_keys_for_window(
        tuple(data.source_statuses), birth_date, start_date, end_date
    )
    for key in relevant_keys:
        feed = data.source_statuses[key]
        if feed.covers_through(end_date):
            continue
        label = source_label(key)
        if feed.parsed_count != feed.source_count:
            warnings.append(
                f"{label} published {feed.source_count} items but only "
                f"{feed.parsed_count} could be parsed"
            )
        elif not feed.ordered:
            warnings.append(f"{label} was not ordered by event date")
        elif feed.last_event_date is None:
            warnings.append(f"{label} did not expose a usable coverage boundary")
        elif feed.type_shard_failures:
            warnings.append(
                f"{label} event-type expansion failed for "
                f"{len(feed.type_shard_failures)} official feeds; later events "
                "in this digest week may be missing"
            )
        elif feed.type_shards_queried:
            warnings.append(
                f"{label} remained limited after querying "
                f"{feed.type_shards_queried} official event types; later events "
                "in this digest week may be missing"
            )
        else:
            warnings.append(
                f"{label} reached its {feed.source_count}-item limit through "
                f"{feed.last_event_date:%B} {feed.last_event_date.day}; later events "
                "in this digest week may be missing"
            )
    return warnings


def supplemental_coverage(
    data: LibraryData,
    birth_date: date,
    start_date: date,
    end_date: date,
) -> tuple[list[str], list[str]]:
    """Return supplemental-age failures separately from feed-cap limitations."""

    failures = [
        f"{source_label(key)} could not be loaded: {data.source_errors[key]}"
        for key in supplemental_source_keys(
            tuple(data.source_errors), birth_date, start_date, end_date
        )
    ]
    limitations: list[str] = []
    for key in supplemental_source_keys(
        tuple(data.source_statuses), birth_date, start_date, end_date
    ):
        feed = data.source_statuses[key]
        if feed.parsed_count != feed.source_count:
            failures.append(
                f"{source_label(key)} published {feed.source_count} items but only "
                f"{feed.parsed_count} could be parsed"
            )
        elif not feed.ordered:
            failures.append(f"{source_label(key)} was not ordered by event date")
        elif feed.type_shard_failures:
            failures.append(
                f"{source_label(key)} event-type expansion failed for "
                f"{len(feed.type_shard_failures)} official feeds"
            )
        elif not feed.covers_through(end_date):
            boundary = (
                f"{feed.last_event_date:%B} {feed.last_event_date.day}"
                if feed.last_event_date
                else "an unknown date"
            )
            limitations.append(
                f"{source_label(key)} "
                + (
                    f"remained limited after querying {feed.type_shards_queried} "
                    "official event types"
                    if feed.type_shards_queried
                    else f"reached its {feed.source_count}-item limit through {boundary}"
                )
                + "; later broadly inclusive events may be missing"
            )
    return failures, limitations


class LibraryDataCoordinator(DataUpdateCoordinator[LibraryData]):
    """Coordinate polling across the selected branch feeds."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: LibraryClient,
        branches: Sequence[Branch],
        birth_date: date,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=update_interval,
            always_update=False,
        )
        self._client = client
        self.branches = tuple(branches)
        self.birth_date = birth_date

    async def _async_update_data(self) -> LibraryData:
        """Fetch every selected branch, retaining partial successes."""

        today = dt_util.now().date()
        coverage_end = next_week_start(today) + timedelta(days=6)
        age_categories = source_age_categories_for_window(
            self.birth_date,
            today,
            today + SOURCE_AGE_HORIZON,
        )
        requests = tuple(
            (branch, age_category)
            for branch in self.branches
            for age_category in age_categories
        )
        results = await asyncio.gather(
            *(
                self._client.async_fetch_feed(branch, age_category)
                for branch, age_category in requests
            ),
            return_exceptions=True,
        )
        statuses: dict[str, BranchFeed] = {}
        errors: dict[str, str] = {}
        for (branch, age_category), result in zip(requests, results, strict=True):
            key = source_key(branch, age_category)
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                errors[key] = str(result) or f"Unable to load {source_label(key)}"
                continue
            feed = result
            if not isinstance(feed, BranchFeed):
                errors[key] = f"Unexpected response from {source_label(key)}"
                continue
            statuses[key] = feed

        if not statuses:
            raise UpdateFailed(
                "; ".join(errors.values()) or "No selected library feed could be loaded"
            )

        request_by_key = {
            source_key(branch, age_category): (branch, age_category)
            for branch, age_category in requests
        }
        expansion_keys = type_expansion_source_keys(
            statuses,
            self.birth_date,
            today,
            coverage_end,
        )
        expanded_results = await asyncio.gather(
            *(
                self._client.async_expand_feed(
                    *request_by_key[key], statuses[key], coverage_end
                )
                for key in expansion_keys
            ),
            return_exceptions=True,
        )
        for key, result in zip(expansion_keys, expanded_results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                _LOGGER.warning("Unable to expand %s: %s", source_label(key), result)
                statuses[key] = replace(
                    statuses[key],
                    type_shards_queried=len(OFFICIAL_EVENT_TYPES),
                    type_shard_failures=(str(result) or "unexpected failure",),
                )
                continue
            if isinstance(result, BranchFeed):
                statuses[key] = result
                continue
            _LOGGER.warning("Unexpected expansion response from %s", source_label(key))
            statuses[key] = replace(
                statuses[key],
                type_shards_queried=len(OFFICIAL_EVENT_TYPES),
                type_shard_failures=("unexpected response",),
            )

        events = [event for feed in statuses.values() for event in feed.events]
        merged_events = merge_events(events)
        merged_events.sort(
            key=lambda event: (event.starts_at, event.branch.name, event.title)
        )
        successful_branches = {key.split(":", 1)[0] for key in statuses}
        counts = {
            branch.code: sum(
                event.branch.code == branch.code for event in merged_events
            )
            for branch in self.branches
            if branch.code in successful_branches
        }
        return LibraryData(
            events=tuple(merged_events),
            source_counts=counts,
            source_statuses=statuses,
            source_errors=errors,
            fetched_at=dt_util.utcnow(),
        )
