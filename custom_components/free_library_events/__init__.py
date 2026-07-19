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
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    NAME,
    SERVICE_RENDER_DIGEST,
)
from .coordinator import (
    LibraryDataCoordinator,
    coverage_warnings,
    supplemental_coverage,
    source_expansion_details,
    source_keys_for_window,
    source_label,
)
from .digest import BRANCHES, build_digest, next_week_start
from .runtime import LibraryConfigEntry

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
    client = LibraryClient(async_get_clientsession(hass))
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        selected_branches(config),
        date.fromisoformat(config[CONF_BIRTH_DATE]),
        timedelta(seconds=config[CONF_SCAN_INTERVAL]),
    )
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Unload the integration entities."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_render_digest(call: ServiceCall) -> ServiceResponse:
    """Refresh source data and return an email payload with coverage metadata."""

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
    coordinator = entry.runtime_data
    if call.data[ATTR_FORCE_REFRESH]:
        await coordinator.async_request_refresh()
        if not coordinator.last_update_success:
            raise HomeAssistantError(
                "The library feeds could not be refreshed; no email was generated"
            )
    if coordinator.data is None:
        raise HomeAssistantError("No library event data is available")

    config = entry_config(entry.data, entry.options)
    reference_date = dt_util.now().date()
    branches = selected_branches(config)
    source_counts = {
        BRANCHES[code].name: count
        for code, count in coordinator.data.source_counts.items()
    }
    week_start = next_week_start(reference_date)
    week_end = week_start + timedelta(days=6)
    birth_date = date.fromisoformat(config[CONF_BIRTH_DATE])
    relevant_error_keys = source_keys_for_window(
        tuple(coordinator.data.source_errors), birth_date, week_start, week_end
    )
    source_errors = [source_label(key) for key in relevant_error_keys]
    source_warnings = coverage_warnings(
        coordinator.data, birth_date, week_start, week_end
    )
    supplemental_failures, supplemental_limitations = supplemental_coverage(
        coordinator.data, birth_date, week_start, week_end
    )
    source_warnings.extend(supplemental_failures)
    response = build_digest(
        child_name=config[CONF_CHILD_NAME],
        birth_date=birth_date,
        filter_mode=config[CONF_FILTER_MODE],
        duration_minutes=config[CONF_CALENDAR_DURATION],
        selected_branches=branches,
        reference_date=reference_date,
        events=coordinator.data.events,
        source_counts=source_counts,
        source_errors=source_errors,
        source_warnings=source_warnings,
        supplemental_age_failures=supplemental_failures,
        supplemental_age_limitations=supplemental_limitations,
    )
    response["metadata"]["expanded_capped_sources"] = source_expansion_details(
        coordinator.data
    )
    response["metadata"]["fetched_at"] = coordinator.data.fetched_at.isoformat()
    return response
