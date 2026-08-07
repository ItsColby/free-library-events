"""Diagnostic status sensor for Free Library Events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .config import entry_config
from .const import CONF_BIRTH_DATE, CONF_FILTER_MODE, DOMAIN
from .coordinator import (
    LibraryData,
    LibraryDataCoordinator,
    coverage_warnings,
    source_expansion_details,
    source_keys_for_window,
    source_label,
    supplemental_coverage,
)
from .digest import (
    BRANCHES,
    classify_event,
    event_is_active,
    include_fit,
    next_week_start,
)
from .entity import service_device_info
from .runtime import LibraryConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, slots=True)
class _ExpandedSourceProjection:
    """Immutable status fields for one expanded capped source."""

    label: str
    discovered_event_count: int
    type_feeds_queried: int
    type_feed_failure_count: int
    type_feed_failure_examples: tuple[str, ...]
    coverage_through: str | None


@dataclass(frozen=True, slots=True)
class _StatusProjection:
    """Immutable state derived from one cached-data evaluation."""

    state: str | None
    cached_events: int
    next_week_events: int
    last_refresh: str | None = None
    cached_events_by_branch: tuple[tuple[str, int], ...] = ()
    current_age_coverage_complete: bool | None = None
    supplemental_age_coverage_complete: bool | None = None
    current_age_coverage_warnings: tuple[str, ...] = ()
    supplemental_age_failures: tuple[str, ...] = ()
    supplemental_age_limitations: tuple[str, ...] = ()
    expanded_capped_sources: tuple[_ExpandedSourceProjection, ...] = ()
    unavailable_current_age_sources: tuple[str, ...] = ()

    def attributes(self) -> dict[str, object]:
        """Return fresh Home Assistant attributes from the immutable snapshot."""

        attributes: dict[str, object] = {
            "cached_events": self.cached_events,
            "next_week_events": self.next_week_events,
        }
        if self.last_refresh is None:
            return attributes
        attributes.update(
            {
                "last_refresh": self.last_refresh,
                "cached_events_by_branch": dict(self.cached_events_by_branch),
                "current_age_coverage_complete": (self.current_age_coverage_complete),
                "supplemental_age_coverage_complete": (
                    self.supplemental_age_coverage_complete
                ),
                "current_age_coverage_warnings": list(
                    self.current_age_coverage_warnings
                ),
                "supplemental_age_failures": list(self.supplemental_age_failures),
                "supplemental_age_limitations": list(self.supplemental_age_limitations),
                "expanded_capped_sources": {
                    source.label: {
                        "discovered_event_count": source.discovered_event_count,
                        "type_feeds_queried": source.type_feeds_queried,
                        "type_feed_failure_count": source.type_feed_failure_count,
                        "type_feed_failure_examples": list(
                            source.type_feed_failure_examples
                        ),
                        "coverage_through": source.coverage_through,
                    }
                    for source in self.expanded_capped_sources
                },
                "unavailable_current_age_sources": list(
                    self.unavailable_current_age_sources
                ),
            }
        )
        return attributes


def _next_projection_deadline(now: datetime, time_zone: tzinfo) -> datetime:
    """Return the next Tuesday midnight in Home Assistant's local timezone."""

    local_now = now.astimezone(time_zone)
    days_until_tuesday = (1 - local_now.weekday()) % 7
    if days_until_tuesday == 0:
        days_until_tuesday = 7
    boundary_date = local_now.date() + timedelta(days=days_until_tuesday)
    return datetime.combine(boundary_date, time.min, tzinfo=time_zone)


def _expanded_source_projection(
    data: LibraryData,
) -> tuple[_ExpandedSourceProjection, ...]:
    """Freeze expanded-source details used by the status attributes."""

    details_by_source = source_expansion_details(data)
    return tuple(
        _ExpandedSourceProjection(
            label=label,
            discovered_event_count=cast(int, details["discovered_event_count"]),
            type_feeds_queried=cast(int, details["type_feeds_queried"]),
            type_feed_failure_count=cast(int, details["type_feed_failure_count"]),
            type_feed_failure_examples=tuple(
                cast(list[str], details["type_feed_failure_examples"])
            ),
            coverage_through=cast(str | None, details["coverage_through"]),
        )
        for label, details in details_by_source.items()
    )


def _build_status_projection(
    data: LibraryData | None,
    last_update_success: bool,
    birth_date: date,
    filter_mode: str,
    evaluation_time: datetime,
) -> _StatusProjection:
    """Build one bounded status projection from cached coordinator data."""

    if data is None:
        return _StatusProjection(
            state="error" if not last_update_success else None,
            cached_events=0,
            next_week_events=0,
        )

    week_start = next_week_start(evaluation_time.date())
    week_end = week_start + timedelta(days=6)
    warnings = coverage_warnings(data, birth_date, week_start, week_end)
    supplemental_failures, supplemental_limitations = supplemental_coverage(
        data, birth_date, week_start, week_end
    )
    relevant_error_keys = source_keys_for_window(
        tuple(data.source_errors), birth_date, week_start, week_end
    )
    next_week_events = sum(
        1
        for event in data.events
        if week_start <= event.event_date <= week_end
        and event_is_active(event)
        and include_fit(classify_event(event, birth_date), filter_mode)
    )
    if not last_update_success:
        state = "error"
    elif relevant_error_keys or warnings or supplemental_failures:
        state = "partial"
    elif supplemental_limitations:
        state = "limited"
    else:
        state = "ok"
    return _StatusProjection(
        state=state,
        cached_events=len(data.events),
        next_week_events=next_week_events,
        last_refresh=data.fetched_at.isoformat(),
        cached_events_by_branch=tuple(
            (BRANCHES[code].name, count) for code, count in data.source_counts.items()
        ),
        current_age_coverage_complete=not warnings and not relevant_error_keys,
        supplemental_age_coverage_complete=(
            not supplemental_failures and not supplemental_limitations
        ),
        current_age_coverage_warnings=tuple(warnings),
        supplemental_age_failures=tuple(supplemental_failures),
        supplemental_age_limitations=tuple(supplemental_limitations),
        expanded_capped_sources=_expanded_source_projection(data),
        unavailable_current_age_sources=tuple(
            source_label(key) for key in relevant_error_keys
        ),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the source-health status sensor."""

    async_add_entities([LibraryStatusSensor(entry, entry.runtime_data)])


class LibraryStatusSensor(CoordinatorEntity[LibraryDataCoordinator], SensorEntity):
    """Compact operator status with useful nontechnical attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, entry: LibraryConfigEntry, coordinator: LibraryDataCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_status"
        self._attr_options = ["ok", "limited", "partial", "error"]
        config = entry_config(entry.data, entry.options)
        self._birth_date = date.fromisoformat(config[CONF_BIRTH_DATE])
        self._filter_mode = str(config[CONF_FILTER_MODE])
        self._time_zone_name = coordinator.hass.config.time_zone
        self._time_zone = dt_util.get_default_time_zone()
        evaluation_time = dt_util.now(self._time_zone)
        self._projection = _build_status_projection(
            coordinator.data,
            coordinator.last_update_success,
            self._birth_date,
            self._filter_mode,
            evaluation_time,
        )
        self._cancel_projection_deadline: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        """Keep diagnostic state visible when a refresh fails."""

        return True

    @property
    def device_info(self) -> DeviceInfo:
        """Return the integration's user-facing device."""

        return service_device_info()

    @property
    def native_value(self) -> str | None:
        return self._projection.state

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return self._projection.attributes()

    async def async_added_to_hass(self) -> None:
        """Start the local projection boundary with the entity lifecycle."""

        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_CORE_CONFIG_UPDATE,
                self._handle_core_config_update,
            )
        )
        self._time_zone_name = self.hass.config.time_zone
        self._time_zone = dt_util.get_default_time_zone()
        evaluation_time = dt_util.now(self._time_zone)
        self._update_projection(evaluation_time)
        self._schedule_projection_deadline(evaluation_time)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the local projection boundary when the entity unloads."""

        self._cancel_scheduled_projection()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Rebuild and reschedule the snapshot after a source refresh."""

        evaluation_time = dt_util.now(self._time_zone)
        projection_changed = self._update_projection(evaluation_time)
        self._schedule_projection_deadline(evaluation_time)
        if projection_changed:
            self.async_write_ha_state()

    @callback
    def _handle_core_config_update(self, _event: Event[dict[str, Any]]) -> None:
        """Rebuild and reschedule when Home Assistant's timezone changes."""

        if self._time_zone_name == self.hass.config.time_zone:
            return
        self._time_zone_name = self.hass.config.time_zone
        self._time_zone = dt_util.get_default_time_zone()
        evaluation_time = dt_util.now(self._time_zone)
        projection_changed = self._update_projection(evaluation_time)
        self._schedule_projection_deadline(evaluation_time)
        if projection_changed:
            self.async_write_ha_state()

    @callback
    def _handle_projection_deadline(self, now: datetime) -> None:
        """Rebuild cached status at the I/O-free Tuesday boundary."""

        self._cancel_projection_deadline = None
        evaluation_time = now.astimezone(self._time_zone)
        projection_changed = self._update_projection(evaluation_time)
        self._schedule_projection_deadline(evaluation_time)
        if projection_changed:
            self.async_write_ha_state()

    @callback
    def _update_projection(self, evaluation_time: datetime) -> bool:
        """Replace the cached snapshot and report whether HA-visible data changed."""

        projection = _build_status_projection(
            self.coordinator.data,
            self.coordinator.last_update_success,
            self._birth_date,
            self._filter_mode,
            evaluation_time,
        )
        if projection == self._projection:
            return False
        self._projection = projection
        return True

    @callback
    def _schedule_projection_deadline(self, evaluation_time: datetime) -> None:
        """Schedule the next local Tuesday midnight without requesting source I/O."""

        self._cancel_scheduled_projection()
        deadline = _next_projection_deadline(evaluation_time, self._time_zone)
        self._cancel_projection_deadline = async_track_point_in_time(
            self.hass,
            self._handle_projection_deadline,
            deadline,
        )

    @callback
    def _cancel_scheduled_projection(self) -> None:
        """Cancel the currently scheduled projection callback, if any."""

        if self._cancel_projection_deadline is None:
            return
        self._cancel_projection_deadline()
        self._cancel_projection_deadline = None
