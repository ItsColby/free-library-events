"""Diagnostic status sensor for Free Library Events."""

from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .config import entry_config
from .const import CONF_BIRTH_DATE, CONF_FILTER_MODE, DOMAIN
from .digest import BRANCHES, classify_event, include_fit
from .entity import service_device_info
from .runtime import LibraryConfigEntry, LibraryRuntime

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

    def __init__(self, entry: LibraryConfigEntry, runtime: LibraryRuntime) -> None:
        super().__init__(runtime.coordinator)
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
        if self.coordinator.data and self.coordinator.data.source_errors:
            return "partial"
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
        matched = sum(
            1
            for event in data.events
            if event.event_date >= today
            and include_fit(classify_event(event, birth_date), filter_mode)
        )
        return {
            "cached_events": len(data.events),
            "matched_events": matched,
            "last_refresh": data.fetched_at.isoformat(),
            "source_counts": {
                BRANCHES[code].name: count for code, count in data.source_counts.items()
            },
            "unavailable_branches": [
                BRANCHES[code].name for code in data.source_errors
            ],
        }
