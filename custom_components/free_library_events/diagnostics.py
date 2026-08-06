"""Privacy-preserving diagnostics for Free Library Events."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .config import entry_config
from .const import CONF_BIRTH_DATE, CONF_CHILD_NAME
from .coordinator import LibraryDataCoordinator, source_label
from .runtime import LibraryConfigEntry

TO_REDACT = {CONF_CHILD_NAME, CONF_BIRTH_DATE}


def _isoformat_optional(value: date | None) -> str | None:
    """Serialize an optional date without weakening diagnostics typing."""

    return value.isoformat() if value is not None else None


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
) -> dict[str, Any]:
    """Return source health without the person's identity or birth date."""

    del hass
    coordinator: LibraryDataCoordinator | None = getattr(entry, "runtime_data", None)
    data = coordinator.data if coordinator else None
    source_statuses = data.source_statuses if data else {}
    source_errors = data.source_errors if data else {}
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
                "published_item_count": source_statuses[key].source_count
                if key in source_statuses
                else None,
                "parsed_item_count": source_statuses[key].parsed_count
                if key in source_statuses
                else None,
                "last_event_date": _isoformat_optional(
                    source_statuses[key].last_event_date
                )
                if key in source_statuses
                else None,
                "ordered": source_statuses[key].ordered
                if key in source_statuses
                else None,
                "discovered_event_count": len(source_statuses[key].events)
                if key in source_statuses
                else None,
                "type_feeds_queried": source_statuses[key].type_shards_queried
                if key in source_statuses
                else 0,
                "type_feed_failures": list(source_statuses[key].type_shard_failures)
                if key in source_statuses
                else [],
                "expanded_through": _isoformat_optional(
                    source_statuses[key].expanded_through
                )
                if key in source_statuses
                else None,
                "available": key not in source_errors,
                "error": source_errors.get(key),
            }
            for key in dict.fromkeys((*source_statuses, *source_errors))
        },
        "cached_event_count": len(data.events) if data else 0,
    }
    return async_redact_data(diagnostics, TO_REDACT)
