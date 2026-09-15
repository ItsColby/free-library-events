"""Age-aware Free Library events calendar."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .calendar_data import (
    LIBRARY_TIME_ZONE,
    LibraryCalendarItem,
    build_calendar_items,
)
from .config import entry_config
from .const import DOMAIN
from .coordinator import LibraryDataCoordinator
from .entity import service_device_info
from .runtime import LibraryConfigEntry

PARALLEL_UPDATES = 0


def _as_calendar_event(item: LibraryCalendarItem) -> CalendarEvent:
    """Convert a selected shared item into its native calendar representation."""

    return CalendarEvent(
        start=item.start,
        end=item.end,
        summary=item.summary,
        description=item.description,
        location=item.location,
        uid=item.uid,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the age-filtered calendar entity."""

    async_add_entities([LibraryCalendar(entry, entry.runtime_data)])


class LibraryCalendar(CoordinatorEntity[LibraryDataCoordinator], CalendarEntity):
    """Calendar containing only events matching the configured person's age."""

    _attr_has_entity_name = True
    _attr_translation_key = "events"

    def __init__(
        self, entry: LibraryConfigEntry, coordinator: LibraryDataCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_calendar"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the integration's user-facing device."""

        return service_device_info()

    @property
    def _config(self) -> dict[str, object]:
        return entry_config(self._entry.data, self._entry.options)

    def _calendar_items(self) -> tuple[LibraryCalendarItem, ...]:
        source_events = self.coordinator.data.events if self.coordinator.data else ()
        return build_calendar_items(source_events, self._config)

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next age-matched event."""

        now = dt_util.now(LIBRARY_TIME_ZONE)
        item = next(
            (item for item in self._calendar_items() if item.end > now),
            None,
        )
        return _as_calendar_event(item) if item is not None else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return age-matched events overlapping the requested range."""

        del hass
        return [
            _as_calendar_event(item)
            for item in self._calendar_items()
            if item.end > start_date and item.start < end_date
        ]
