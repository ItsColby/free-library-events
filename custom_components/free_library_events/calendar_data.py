"""Deterministic age-filtered calendar event projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .const import (
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_FILTER_MODE,
)
from .digest import (
    TIMEZONE,
    Event,
    classify_event,
    event_calendar_location,
    event_details_url,
    event_identity,
    event_is_active,
    include_fit,
    related_link_lines,
)

LIBRARY_TIME_ZONE = ZoneInfo(TIMEZONE)


@dataclass(frozen=True, slots=True)
class LibraryCalendarItem:
    """One filtered event shared by the HA calendar and iCalendar feed."""

    start: datetime
    end: datetime
    summary: str
    description: str
    location: str
    uid: str
    url: str


def build_calendar_items(
    events: Iterable[Event], config: Mapping[str, object]
) -> tuple[LibraryCalendarItem, ...]:
    """Project normalized source events into deterministic calendar items."""

    birth_date = date.fromisoformat(str(config[CONF_BIRTH_DATE]))
    filter_mode = str(config[CONF_FILTER_MODE])
    duration = int(config[CONF_CALENDAR_DURATION])
    items: list[LibraryCalendarItem] = []
    for event in events:
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
        details_url = event_details_url(event)
        description_parts = [
            event.description,
            *related_link_lines(event),
            f"Official details: {details_url}",
        ]
        if end_note:
            description_parts.append(end_note)
        items.append(
            LibraryCalendarItem(
                start=start,
                end=end,
                summary=event.title,
                description="\n\n".join(description_parts),
                location=event_calendar_location(event),
                uid=event_identity(event),
                url=details_url,
            )
        )
    return tuple(items)
