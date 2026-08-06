"""Manual refresh button for Free Library Events."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LibraryDataCoordinator
from .entity import service_device_info
from .runtime import LibraryConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the manual refresh button."""

    async_add_entities([LibraryRefreshButton(entry.runtime_data)])


class LibraryRefreshButton(CoordinatorEntity[LibraryDataCoordinator], ButtonEntity):
    """Request an immediate refresh of the selected branch feeds."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh_events"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: LibraryDataCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_refresh"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the integration's user-facing device."""

        return service_device_info()

    async def async_press(self) -> None:
        """Refresh the selected official feeds now."""

        await self.coordinator.async_request_refresh()
        if not self.coordinator.last_update_success:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="manual_refresh_failed",
            )
