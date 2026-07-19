"""Age-aware Free Library events calendar."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .config import entry_config
from .const import (
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_FILTER_MODE,
    DOMAIN,
)
from .coordinator import LibraryDataCoordinator
from .digest import (
    TIMEZONE,
    Event,
    classify_event,
    event_calendar_location,
    event_details_url,
    event_is_active,
    include_fit,
    related_link_lines,
)
from .entity import service_device_info
from .runtime import LibraryConfigEntry

PARALLEL_UPDATES = 0
LIBRARY_TIME_ZONE = ZoneInfo(TIMEZONE)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the age-filtered calendar entity."""

    async_add_entities([LibraryCalendar(entry, entry.runtime_data)])


class LibraryCalendar(CoordinatorEntity, CalendarEntity):
    """Calendar containing only events matching the child's age."""

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
        config = self._config
        birth_date = date.fromisoformat(config[CONF_BIRTH_DATE])
        filter_mode = config[CONF_FILTER_MODE]
        duration = config[CONF_CALENDAR_DURATION]
        events: list[CalendarEvent] = []
        for event in self.coordinator.data.events if self.coordinator.data else ():
            if not event_is_active(event):
                continue
            fit = classify_event(event, birth_date)
            if not include_fit(fit, filter_mode):
                continue
            start = event.starts_at.replace(tzinfo=LIBRARY_TIME_ZONE)
            if event.end_at:
                end = event.end_at.replace(tzinfo=LIBRARY_TIME_ZONE)
                end_note = None
            else:
                end = start + timedelta(minutes=duration)
                end_note = (
                    f"End time not published in the feed; using a {duration}-minute "
                    "placeholder."
                )
            description_parts = [
                event.description,
                *related_link_lines(event),
                f"Official details: {event_details_url(event)}",
            ]
            if end_note:
                description_parts.append(end_note)
            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=event.title,
                    description="\n\n".join(description_parts),
                    location=event_calendar_location(event),
                    uid=event.link or self._event_uid(event),
                )
            )
        return events

    @staticmethod
    def _event_uid(event: Event) -> str:
        return (
            f"{event.branch.code}:{event.event_date.isoformat()}:"
            f"{event.start_time.isoformat()}:{event.title}"
        )

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
