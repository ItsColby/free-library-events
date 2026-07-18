"""Manual refresh button for Free Library Events."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .entity import service_device_info
from .runtime import LibraryConfigEntry, LibraryRuntime

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the manual refresh button."""

    async_add_entities([LibraryRefreshButton(entry.runtime_data)])


class LibraryRefreshButton(CoordinatorEntity, ButtonEntity):
    """Request an immediate refresh of both selected branch feeds."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_events"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime: LibraryRuntime) -> None:
        super().__init__(runtime.coordinator)
        self._attr_unique_id = f"{DOMAIN}_refresh"

    @property
    def device_info(self):
        return service_device_info()

    async def async_press(self) -> None:
        """Refresh the selected official feeds now."""

        await self.coordinator.async_request_refresh()
