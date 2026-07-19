"""Privacy-preserving diagnostics for Free Library Events."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .config import entry_config
from .const import CONF_BIRTH_DATE, CONF_CHILD_NAME
from .coordinator import LibraryDataCoordinator, source_label
from .runtime import LibraryConfigEntry

TO_REDACT = {CONF_CHILD_NAME, CONF_BIRTH_DATE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
) -> dict[str, Any]:
    """Return source health and counts without the child's identity or birth date."""

    del hass
    coordinator: LibraryDataCoordinator | None = getattr(entry, "runtime_data", None)
    data = coordinator.data if coordinator else None
    diagnostics = {
        "config": entry_config(entry.data, entry.options),
        "coordinator": {
            "last_update_success": coordinator.last_update_success
            if coordinator
            else None,
            "last_exception": str(coordinator.last_exception)
            if coordinator and coordinator.last_exception
            else None,
            "fetched_at": data.fetched_at.isoformat() if data else None,
        },
        "sources": {
            source_label(key): {
                "published_item_count": data.source_statuses[key].source_count
                if key in data.source_statuses
                else None,
                "parsed_item_count": data.source_statuses[key].parsed_count
                if key in data.source_statuses
                else None,
                "last_event_date": data.source_statuses[key].last_event_date.isoformat()
                if key in data.source_statuses
                and data.source_statuses[key].last_event_date
                else None,
                "ordered": data.source_statuses[key].ordered
                if key in data.source_statuses
                else None,
                "discovered_event_count": len(data.source_statuses[key].events)
                if key in data.source_statuses
                else None,
                "type_feeds_queried": data.source_statuses[key].type_shards_queried
                if key in data.source_statuses
                else 0,
                "type_feed_failures": list(
                    data.source_statuses[key].type_shard_failures
                )
                if key in data.source_statuses
                else [],
                "expanded_through": data.source_statuses[
                    key
                ].expanded_through.isoformat()
                if key in data.source_statuses
                and data.source_statuses[key].expanded_through
                else None,
                "available": key not in data.source_errors,
                "error": data.source_errors.get(key),
            }
            for key in dict.fromkeys(
                (
                    *(data.source_statuses if data else {}),
                    *(data.source_errors if data else {}),
                )
            )
        },
        "cached_event_count": len(data.events) if data else 0,
    }
    return async_redact_data(diagnostics, TO_REDACT)
