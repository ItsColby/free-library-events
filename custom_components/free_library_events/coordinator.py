"""Data coordinator for Free Library Events."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    OFFICIAL_EVENT_TYPES,
    RSS_ITEM_LIMIT,
    SOURCE_ERROR_EXPANSION_TIMEOUT,
    SOURCE_ERROR_REQUEST_FAILED,
    SOURCE_ERROR_UNEXPECTED,
    TYPE_SHARD_BLOCKER_CAPPED,
    TYPE_SHARD_BLOCKER_PARSE_INCOMPLETE,
    TYPE_SHARD_BLOCKER_UNORDERED,
    TYPE_SHARD_INTEGRITY_BLOCKERS,
    BranchFeed,
    LibraryApiError,
    LibraryClient,
    TypeShardBlocker,
    source_error_category,
    source_error_description,
)
from .const import DOMAIN
from .digest import (
    AGE_CATEGORY_ORDER,
    AGE_CATEGORY_WINDOWS,
    BRANCHES,
    Branch,
    Event,
    age_categories_for_window,
    age_in_months,
    merge_events,
    next_week_start,
    source_age_categories_for_window,
)

_LOGGER = logging.getLogger(__name__)
SOURCE_AGE_HORIZON = timedelta(days=90)
MAX_TYPE_EXPANSIONS_PER_REFRESH = 12
TYPE_EXPANSION_TIMEOUT_SECONDS = 90
MAX_TYPE_FAILURE_EXAMPLES = 3
EXPEDITED_RETRY_SECONDS = 5 * 60


def type_shard_blocker_data(blocker: TypeShardBlocker) -> dict[str, object]:
    """Return privacy-safe structured evidence for one type-feed blocker."""

    return {
        "event_type": blocker.event_type,
        "reason": blocker.reason,
        "published_item_count": blocker.source_count,
        "parsed_item_count": blocker.parsed_count,
        "last_event_date": blocker.last_event_date.isoformat()
        if blocker.last_event_date
        else None,
    }


def _type_shard_blocker_description(blocker: TypeShardBlocker) -> str:
    """Return a bounded operator-facing description of one type-feed blocker."""

    if blocker.reason == TYPE_SHARD_BLOCKER_CAPPED:
        boundary = (
            f"{blocker.last_event_date:%B} {blocker.last_event_date.day}"
            if blocker.last_event_date
            else "an unknown date"
        )
        return (
            f"{blocker.event_type} returned {blocker.source_count} items "
            f"through {boundary}"
        )
    if blocker.reason == TYPE_SHARD_BLOCKER_PARSE_INCOMPLETE:
        return (
            f"{blocker.event_type} published {blocker.source_count} items but only "
            f"{blocker.parsed_count} could be parsed"
        )
    if blocker.reason == TYPE_SHARD_BLOCKER_UNORDERED:
        return f"{blocker.event_type} was not ordered by event date"
    return f"{blocker.event_type} did not expose a usable coverage boundary"


def _type_shard_integrity_blockers(
    feed: BranchFeed,
) -> tuple[TypeShardBlocker, ...]:
    """Return successful type feeds whose evidence is operationally unusable."""

    return tuple(
        blocker
        for blocker in feed.type_shard_blockers
        if blocker.reason in TYPE_SHARD_INTEGRITY_BLOCKERS
    )


def _type_expansion_limitation_reason(feed: BranchFeed, end_date: date) -> str:
    """Explain why a healthy type expansion could not prove the target horizon."""

    reasons = [
        _type_shard_blocker_description(blocker)
        for blocker in feed.type_shard_blockers
        if blocker.reason == TYPE_SHARD_BLOCKER_CAPPED
    ]
    if len(reasons) > MAX_TYPE_FAILURE_EXAMPLES:
        omitted = len(reasons) - MAX_TYPE_FAILURE_EXAMPLES
        reasons = reasons[:MAX_TYPE_FAILURE_EXAMPLES]
        reasons.append(f"{omitted} additional event types were capped")
    if feed.base_prefix_recovered is False:
        reasons.append("the official event types did not recover every base-feed item")
    if not reasons:
        return (
            f"coverage through {end_date:%B} {end_date.day} could not be proven "
            f"after querying {feed.type_shards_queried} official event types"
        )
    return (
        "; ".join(reasons)
        + f"; proving coverage through {end_date:%B} {end_date.day} requires "
        "later complete publisher evidence"
    )


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
    """Return source keys relevant to the configured person's age."""

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
            "type_feed_blocker_count": len(feed.type_shard_blockers),
            "type_feed_blocker_examples": [
                type_shard_blocker_data(blocker)
                for blocker in feed.type_shard_blockers[:MAX_TYPE_FAILURE_EXAMPLES]
            ],
            "base_prefix_recovered": feed.base_prefix_recovered,
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
                and feed.source_count >= RSS_ITEM_LIMIT
                and feed.parsed_count == feed.source_count
                and feed.ordered
                and not feed.covers_through(coverage_end)
            ),
            key=expansion_priority,
        )[:MAX_TYPE_EXPANSIONS_PER_REFRESH]
    )


async def async_expand_source(
    client: LibraryClient,
    branch: Branch,
    age_category: str,
    base_feed: BranchFeed,
    coverage_end: date,
) -> BranchFeed:
    """Expand one capped source without allowing a stalled refresh."""

    try:
        return await asyncio.wait_for(
            client.async_expand_feed(
                branch,
                age_category,
                base_feed,
                coverage_end,
            ),
            timeout=TYPE_EXPANSION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        raise LibraryApiError(SOURCE_ERROR_EXPANSION_TIMEOUT) from None


@dataclass(frozen=True, slots=True)
class LibraryData:
    """Latest normalized events and branch-source health."""

    events: tuple[Event, ...]
    source_counts: Mapping[str, int]
    source_statuses: Mapping[str, BranchFeed]
    source_errors: Mapping[str, str]
    fetched_at: datetime

    def __post_init__(self) -> None:
        """Detach and freeze every nested mapping in the normalized snapshot."""

        object.__setattr__(
            self, "source_counts", MappingProxyType(dict(self.source_counts))
        )
        object.__setattr__(
            self, "source_statuses", MappingProxyType(dict(self.source_statuses))
        )
        object.__setattr__(
            self, "source_errors", MappingProxyType(dict(self.source_errors))
        )


@dataclass(frozen=True, slots=True)
class RefreshAttempt:
    """Privacy-safe evidence from the latest completed base-source attempt."""

    completed_at: datetime
    source_keys: tuple[str, ...]
    source_errors: Mapping[str, str]
    retryable_failure_count: int
    expedited_retry_scheduled: bool

    def __post_init__(self) -> None:
        """Detach and freeze nested attempt evidence."""

        object.__setattr__(
            self, "source_errors", MappingProxyType(dict(self.source_errors))
        )

    @property
    def requested_source_count(self) -> int:
        """Return the number of base sources in this attempt."""

        return len(self.source_keys)

    @property
    def failed_source_count(self) -> int:
        """Return the number of failed base sources in this attempt."""

        return len(self.source_errors)

    @property
    def successful_source_count(self) -> int:
        """Return the number of successful base sources in this attempt."""

        return self.requested_source_count - self.failed_source_count

    @property
    def error_category_counts(self) -> Mapping[str, int]:
        """Return stable allow-listed failure-category counts."""

        return MappingProxyType(
            dict(sorted(Counter(self.source_errors.values()).items()))
        )


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
        elif integrity_blockers := _type_shard_integrity_blockers(feed):
            examples = "; ".join(
                _type_shard_blocker_description(blocker)
                for blocker in integrity_blockers[:MAX_TYPE_FAILURE_EXAMPLES]
            )
            warnings.append(
                f"{label} event-type expansion returned unusable evidence for "
                f"{len(integrity_blockers)} official feeds ({examples}); later events "
                "in this digest week may be missing"
            )
        elif feed.type_shards_queried:
            warnings.append(
                f"{label} remained limited because "
                f"{_type_expansion_limitation_reason(feed, end_date)}; later events "
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
        f"{source_label(key)} could not be loaded: "
        f"{source_error_description(data.source_errors[key])}"
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
        elif integrity_blockers := _type_shard_integrity_blockers(feed):
            examples = "; ".join(
                _type_shard_blocker_description(blocker)
                for blocker in integrity_blockers[:MAX_TYPE_FAILURE_EXAMPLES]
            )
            failures.append(
                f"{source_label(key)} event-type expansion returned unusable "
                f"evidence for {len(integrity_blockers)} official feeds ({examples})"
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
                    "remained limited because "
                    f"{_type_expansion_limitation_reason(feed, end_date)}"
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
        self.last_attempt: RefreshAttempt | None = None
        self._expedited_retry_used = False

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
        retryable_failure_keys: set[str] = set()
        for (branch, age_category), result in zip(requests, results, strict=True):
            key = source_key(branch, age_category)
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                errors[key] = source_error_category(result)
                if (
                    isinstance(result, LibraryApiError)
                    and result.category == SOURCE_ERROR_REQUEST_FAILED
                    and result.retryable
                ):
                    retryable_failure_keys.add(key)
                continue
            feed = result
            if not isinstance(feed, BranchFeed):
                errors[key] = SOURCE_ERROR_UNEXPECTED
                continue
            statuses[key] = feed

        if not statuses:
            all_failures_retryable = len(retryable_failure_keys) == len(requests)
            schedule_expedited_retry = (
                all_failures_retryable and not self._expedited_retry_used
            )
            if schedule_expedited_retry:
                self._expedited_retry_used = True
            completed_at = dt_util.utcnow()
            self.last_attempt = RefreshAttempt(
                completed_at=completed_at,
                source_keys=tuple(
                    source_key(branch, age_category)
                    for branch, age_category in requests
                ),
                source_errors=errors,
                retryable_failure_count=len(retryable_failure_keys),
                expedited_retry_scheduled=schedule_expedited_retry,
            )
            categories = ", ".join(
                f"{category}={count}"
                for category, count in self.last_attempt.error_category_counts.items()
            )
            _LOGGER.warning(
                "All %d library sources failed (%s); expedited retry scheduled: %s",
                len(requests),
                categories,
                schedule_expedited_retry,
            )
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="library_source_update_failed",
                retry_after=(
                    EXPEDITED_RETRY_SECONDS if schedule_expedited_retry else None
                ),
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
                async_expand_source(
                    self._client, *request_by_key[key], statuses[key], coverage_end
                )
                for key in expansion_keys
            ),
            return_exceptions=True,
        )
        for key, result in zip(expansion_keys, expanded_results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                category = source_error_category(result)
                _LOGGER.warning("Unable to expand %s (%s)", source_label(key), category)
                statuses[key] = replace(
                    statuses[key],
                    type_shards_queried=len(OFFICIAL_EVENT_TYPES),
                    type_shard_failures=(category,),
                )
                continue
            if isinstance(result, BranchFeed):
                statuses[key] = result
                continue
            _LOGGER.warning("Unexpected expansion response from %s", source_label(key))
            statuses[key] = replace(
                statuses[key],
                type_shards_queried=len(OFFICIAL_EVENT_TYPES),
                type_shard_failures=(SOURCE_ERROR_UNEXPECTED,),
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
        completed_at = dt_util.utcnow()
        self._expedited_retry_used = False
        self.last_attempt = RefreshAttempt(
            completed_at=completed_at,
            source_keys=tuple(
                source_key(branch, age_category) for branch, age_category in requests
            ),
            source_errors=errors,
            retryable_failure_count=len(retryable_failure_keys),
            expedited_retry_scheduled=False,
        )
        return LibraryData(
            events=tuple(merged_events),
            source_counts=counts,
            source_statuses=statuses,
            source_errors=errors,
            fetched_at=completed_at,
        )


def coordinator_error_category(error: BaseException | None) -> str | None:
    """Return a compact category for the coordinator's last exception."""

    if error is None:
        return None
    if isinstance(error, UpdateFailed):
        return "source_update_failed"
    if isinstance(error, LibraryApiError):
        return "source_request_failed"
    if isinstance(error, TimeoutError):
        return "timeout"
    return "unexpected"
