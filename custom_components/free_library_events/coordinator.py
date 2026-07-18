"""Data coordinator for Free Library Events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Sequence

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import BranchFeed, LibraryClient
from .const import DOMAIN
from .digest import (
    BRANCHES,
    Branch,
    Event,
    age_categories_for_window,
    merge_events,
)

_LOGGER = logging.getLogger(__name__)
SOURCE_AGE_HORIZON = timedelta(days=90)


def source_key(branch: Branch, age_category: str) -> str:
    """Return a stable key for one branch-plus-age feed."""

    return f"{branch.code}:{age_category}"


def source_label(key: str) -> str:
    """Return a human-readable label for a source key."""

    branch_code, age_category = key.split(":", 1)
    return f"{BRANCHES[branch_code].name} — {age_category}"


def source_keys_for_window(
    keys: Sequence[str],
    birth_date: date,
    start_date: date,
    end_date: date,
) -> list[str]:
    """Return source keys relevant to the child's age in a target window."""

    categories = set(age_categories_for_window(birth_date, start_date, end_date))
    return [key for key in keys if key.split(":", 1)[1] in categories]


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
        else:
            warnings.append(
                f"{label} reached its {feed.source_count}-item limit through "
                f"{feed.last_event_date:%B} {feed.last_event_date.day}; later events "
                "in this digest week may be missing"
            )
    return warnings


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
        age_categories = age_categories_for_window(
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
        events: list[Event] = []
        statuses: dict[str, BranchFeed] = {}
        errors: dict[str, str] = {}
        for (branch, age_category), result in zip(requests, results, strict=True):
            key = source_key(branch, age_category)
            if isinstance(result, BaseException):
                errors[key] = str(result) or f"Unable to load {source_label(key)}"
                continue
            feed = result
            if not isinstance(feed, BranchFeed):
                errors[key] = f"Unexpected response from {source_label(key)}"
                continue
            events.extend(feed.events)
            statuses[key] = feed

        if not statuses:
            raise UpdateFailed(
                "; ".join(errors.values()) or "No selected library feed could be loaded"
            )

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
