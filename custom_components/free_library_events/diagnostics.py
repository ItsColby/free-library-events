"""Privacy-preserving diagnostics for Free Library Events."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .config import entry_config
from .const import CONF_BIRTH_DATE, CONF_CHILD_NAME
from .digest import BRANCHES
from .runtime import LibraryConfigEntry, LibraryRuntime

TO_REDACT = {CONF_CHILD_NAME, CONF_BIRTH_DATE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
) -> dict[str, Any]:
    """Return source health and counts without the child's identity or birth date."""

    del hass
    runtime: LibraryRuntime | None = getattr(entry, "runtime_data", None)
    data = runtime.coordinator.data if runtime else None
    diagnostics = {
        "config": entry_config(entry.data, entry.options),
        "coordinator": {
            "last_update_success": runtime.coordinator.last_update_success
            if runtime
            else None,
            "last_exception": str(runtime.coordinator.last_exception)
            if runtime and runtime.coordinator.last_exception
            else None,
            "fetched_at": data.fetched_at.isoformat() if data else None,
        },
        "sources": {
            BRANCHES[code].name: {
                "published_item_count": data.source_counts.get(code),
                "available": code not in data.source_errors,
                "error": data.source_errors.get(code),
            }
            for code in BRANCHES
            if code
            in {
                *(data.source_counts if data else {}),
                *(data.source_errors if data else {}),
            }
        },
        "cached_event_count": len(data.events) if data else 0,
    }
    return async_redact_data(diagnostics, TO_REDACT)
