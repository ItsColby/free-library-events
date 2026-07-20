"""Age-aware Free Library events calendar."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .config import entry_config
from .calendar_data import LIBRARY_TIME_ZONE, build_calendar_items
from .const import DOMAIN
from .coordinator import LibraryDataCoordinator
from .entity import service_device_info
from .runtime import LibraryConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the age-filtered calendar entity."""

    async_add_entities([LibraryCalendar(entry, entry.runtime_data)])


class LibraryCalendar(CoordinatorEntity, CalendarEntity):
    """Calendar containing only events matching the configured person's age."""

    _attr_has_entity_name = True
    _attr_translation_key = "events"
    _attr_icon = "mdi:library"

    def __init__(
        self, entry: LibraryConfigEntry, coordinator: LibraryDataCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_calendar"

    @property
    def device_info(self):
        """Return the integration's user-facing device."""

        return service_device_info()

    @property
    def _config(self) -> dict[str, object]:
        return entry_config(self._entry.data, self._entry.options)

    def _calendar_events(self) -> list[CalendarEvent]:
        source_events = self.coordinator.data.events if self.coordinator.data else ()
        return [
            CalendarEvent(
                start=item.start,
                end=item.end,
                summary=item.summary,
                description=item.description,
                location=item.location,
                uid=item.uid,
            )
            for item in build_calendar_items(source_events, self._config)
        ]

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next age-matched event."""

        now = dt_util.now(LIBRARY_TIME_ZONE)
        return next(
            (event for event in self._calendar_events() if event.end > now),
            None,
        )

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return age-matched events overlapping the requested range."""

        del hass
        return [
            event
            for event in self._calendar_events()
            if event.end > start_date and event.start < end_date
        ]
