"""Native Home Assistant integration for Free Library events."""

from __future__ import annotations

from datetime import date, timedelta
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import LibraryClient
from .config import entry_config, selected_branches
from .const import (
    ATTR_FORCE_REFRESH,
    ATTR_REFERENCE_DATE,
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    NAME,
    SERVICE_RENDER_DIGEST,
)
from .coordinator import LibraryDataCoordinator
from .digest import BRANCHES, build_digest
from .runtime import LibraryConfigEntry, LibraryRuntime

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.SENSOR,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

RENDER_DIGEST_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_FORCE_REFRESH, default=True): cv.boolean,
        vol.Optional(ATTR_REFERENCE_DATE): cv.date,
    }
)


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:
    """Register the native response-returning digest action."""

    del config
    if not hass.services.has_service(DOMAIN, SERVICE_RENDER_DIGEST):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            _async_render_digest,
            schema=RENDER_DIGEST_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Set up a Free Library Events config entry."""

    if entry.title != NAME:
        hass.config_entries.async_update_entry(entry, title=NAME)
    config = entry_config(entry.data, entry.options)
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        LibraryClient(async_get_clientsession(hass)),
        selected_branches(config),
        timedelta(seconds=config[CONF_SCAN_INTERVAL]),
    )
    entry.runtime_data = LibraryRuntime(coordinator)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Unload the integration entities."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_render_digest(call: ServiceCall) -> ServiceResponse:
    """Refresh source data and return a complete email payload."""

    hass = call.hass
    loaded_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
    if len(loaded_entries) != 1:
        raise ServiceValidationError(
            "Free Library Events must have exactly one loaded config entry"
        )

    entry = loaded_entries[0]
    runtime: LibraryRuntime = entry.runtime_data
    coordinator = runtime.coordinator
    if call.data[ATTR_FORCE_REFRESH]:
        await coordinator.async_request_refresh()
        if not coordinator.last_update_success:
            raise HomeAssistantError(
                "The library feeds could not be refreshed; no email was generated"
            )
    if coordinator.data is None:
        raise HomeAssistantError("No library event data is available")

    config = entry_config(entry.data, entry.options)
    reference_date: date = call.data.get(
        ATTR_REFERENCE_DATE,
        dt_util.now().date(),
    )
    branches = selected_branches(config)
    source_counts = {
        BRANCHES[code].name: count
        for code, count in coordinator.data.source_counts.items()
    }
    source_errors = [BRANCHES[code].name for code in coordinator.data.source_errors]
    return build_digest(
        child_name=config[CONF_CHILD_NAME],
        birth_date=date.fromisoformat(config[CONF_BIRTH_DATE]),
        filter_mode=config[CONF_FILTER_MODE],
        duration_minutes=config[CONF_CALENDAR_DURATION],
        selected_branches=branches,
        reference_date=reference_date,
        events=coordinator.data.events,
        source_counts=source_counts,
        source_errors=source_errors,
    )
