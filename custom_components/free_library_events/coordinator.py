"""Data coordinator for Free Library Events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Sequence

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import BranchFeed, LibraryClient
from .const import DOMAIN
from .digest import Branch, Event

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LibraryData:
    """Latest normalized events and branch-source health."""

    events: tuple[Event, ...]
    source_counts: dict[str, int]
    source_errors: dict[str, str]
    fetched_at: datetime


class LibraryDataCoordinator(DataUpdateCoordinator[LibraryData]):
    """Coordinate polling across the selected branch feeds."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: LibraryClient,
        branches: Sequence[Branch],
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

    async def _async_update_data(self) -> LibraryData:
        """Fetch every selected branch, retaining partial successes."""

        results = await asyncio.gather(
            *(self._client.async_fetch_branch(branch) for branch in self.branches),
            return_exceptions=True,
        )
        events: list[Event] = []
        counts: dict[str, int] = {}
        errors: dict[str, str] = {}
        for branch, result in zip(self.branches, results, strict=True):
            if isinstance(result, BaseException):
                errors[branch.code] = str(result) or f"Unable to load {branch.name}"
                continue
            feed = result
            if not isinstance(feed, BranchFeed):
                errors[branch.code] = f"Unexpected response from {branch.name}"
                continue
            events.extend(feed.events)
            counts[branch.code] = feed.source_count

        if not counts:
            raise UpdateFailed(
                "; ".join(errors.values()) or "No selected library feed could be loaded"
            )

        events.sort(key=lambda event: (event.starts_at, event.branch.name, event.title))
        return LibraryData(
            events=tuple(events),
            source_counts=counts,
            source_errors=errors,
            fetched_at=dt_util.utcnow(),
        )
