"""Diagnostic status sensor for Free Library Events."""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .config import entry_config
from .const import CONF_BIRTH_DATE, CONF_FILTER_MODE, DOMAIN
from .coordinator import (
    LibraryDataCoordinator,
    coverage_warnings,
    discovery_coverage,
    source_keys_for_window,
    source_label,
)
from .digest import BRANCHES, classify_event, include_fit, next_week_start
from .entity import service_device_info
from .runtime import LibraryConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the source-health status sensor."""

    async_add_entities([LibraryStatusSensor(entry, entry.runtime_data)])


class LibraryStatusSensor(CoordinatorEntity, SensorEntity):
    """Compact operator status with useful nontechnical attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_icon = "mdi:book-check-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, entry: LibraryConfigEntry, coordinator: LibraryDataCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_status"

    @property
    def available(self) -> bool:
        """Keep diagnostic state visible when a refresh fails."""

        return True

    @property
    def _config(self) -> dict[str, object]:
        return entry_config(self._entry.data, self._entry.options)

    @property
    def device_info(self):
        return service_device_info()

    @property
    def native_value(self) -> str:
        if not self.coordinator.last_update_success:
            return "error"
        if self.coordinator.data:
            today = dt_util.now().date()
            week_start = next_week_start(today)
            week_end = week_start + timedelta(days=6)
            birth_date = date.fromisoformat(self._config[CONF_BIRTH_DATE])
            relevant_errors = source_keys_for_window(
                tuple(self.coordinator.data.source_errors),
                birth_date,
                week_start,
                week_end,
            )
            discovery_failures, discovery_limitations = discovery_coverage(
                self.coordinator.data, week_end
            )
            if (
                relevant_errors
                or coverage_warnings(
                    self.coordinator.data, birth_date, week_start, week_end
                )
                or discovery_failures
            ):
                return "partial"
            if discovery_limitations:
                return "limited"
        return "ok" if self.coordinator.data else "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self.coordinator.data
        if data is None:
            return {"cached_events": 0, "matched_events": 0}
        config = self._config
        birth_date = date.fromisoformat(config[CONF_BIRTH_DATE])
        filter_mode = config[CONF_FILTER_MODE]
        today = dt_util.now().date()
        week_start = next_week_start(today)
        week_end = week_start + timedelta(days=6)
        warnings = coverage_warnings(data, birth_date, week_start, week_end)
        discovery_failures, discovery_limitations = discovery_coverage(data, week_end)
        relevant_error_keys = source_keys_for_window(
            tuple(data.source_errors), birth_date, week_start, week_end
        )
        next_week_events = sum(
            1
            for event in data.events
            if week_start <= event.event_date <= week_end
            and include_fit(classify_event(event, birth_date), filter_mode)
        )
        return {
            "cached_events": len(data.events),
            "next_week_events": next_week_events,
            "last_refresh": data.fetched_at.isoformat(),
            "cached_events_by_branch": {
                BRANCHES[code].name: count for code, count in data.source_counts.items()
            },
            "age_feed_coverage_complete": not warnings and not relevant_error_keys,
            "discovery_coverage_complete": not discovery_failures
            and not discovery_limitations,
            "coverage_warnings": warnings,
            "discovery_failures": discovery_failures,
            "discovery_limitations": discovery_limitations,
            "unavailable_sources": [source_label(key) for key in relevant_error_keys],
        }
