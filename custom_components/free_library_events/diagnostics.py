"""Privacy-preserving diagnostics for Free Library Events."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .api import BranchFeed
from .config import entry_config
from .const import CONF_BIRTH_DATE, CONF_CHILD_NAME, CONF_WEBCAL_NAME
from .coordinator import (
    LibraryDataCoordinator,
    coordinator_error_category,
    source_label,
    type_shard_blocker_data,
)
from .runtime import LibraryConfigEntry

TO_REDACT = {CONF_CHILD_NAME, CONF_BIRTH_DATE, CONF_WEBCAL_NAME}


def _isoformat_optional(value: date | None) -> str | None:
    """Serialize an optional date without weakening diagnostics typing."""

    return value.isoformat() if value is not None else None


def _feed_diagnostics(feed: BranchFeed | None) -> dict[str, object]:
    """Project optional retained feed evidence with stable unavailable defaults."""

    return {
        "published_item_count": feed.source_count if feed else None,
        "parsed_item_count": feed.parsed_count if feed else None,
        "last_event_date": _isoformat_optional(feed.last_event_date) if feed else None,
        "ordered": feed.ordered if feed else None,
        "discovered_event_count": len(feed.events) if feed else None,
        "type_feeds_queried": feed.type_shards_queried if feed else 0,
        "type_feed_failures": list(feed.type_shard_failures) if feed else [],
        "type_feed_blockers": [
            type_shard_blocker_data(blocker) for blocker in feed.type_shard_blockers
        ]
        if feed
        else [],
        "base_prefix_recovered": feed.base_prefix_recovered if feed else None,
        "expanded_through": _isoformat_optional(feed.expanded_through)
        if feed
        else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: LibraryConfigEntry,
) -> dict[str, Any]:
    """Return source health without the person's identity or birth date."""

    del hass
    coordinator: LibraryDataCoordinator | None = getattr(entry, "runtime_data", None)
    data = coordinator.data if coordinator else None
    last_attempt = getattr(coordinator, "last_attempt", None)
    source_statuses = data.source_statuses if data else {}
    source_errors = data.source_errors if data else {}
    try:
        config = entry_config(entry.data, entry.options)
    except TypeError, ValueError:
        config = None
    diagnostics = {
        "config": config,
        "config_error_category": "invalid_config" if config is None else None,
        "coordinator": {
            "last_update_success": coordinator.last_update_success
            if coordinator
            else None,
            "last_error_category": coordinator_error_category(
                coordinator.last_exception if coordinator else None
            ),
            "fetched_at": data.fetched_at.isoformat() if data else None,
        },
        "last_attempt": {
            "completed_at": last_attempt.completed_at.isoformat(),
            "requested_source_count": last_attempt.requested_source_count,
            "successful_source_count": last_attempt.successful_source_count,
            "failed_source_count": last_attempt.failed_source_count,
            "retryable_failure_count": last_attempt.retryable_failure_count,
            "error_category_counts": dict(last_attempt.error_category_counts),
            "expedited_retry_scheduled": last_attempt.expedited_retry_scheduled,
            "sources": {
                source_label(key): {
                    "available": key not in last_attempt.source_errors,
                    "error_category": last_attempt.source_errors.get(key),
                }
                for key in last_attempt.source_keys
            },
        }
        if last_attempt
        else None,
        "sources": {
            source_label(key): {
                **_feed_diagnostics(source_statuses.get(key)),
                "available": key not in source_errors,
                "error_category": source_errors.get(key),
            }
            for key in dict.fromkeys((*source_statuses, *source_errors))
        },
        "cached_event_count": len(data.events) if data else 0,
    }
    return async_redact_data(diagnostics, TO_REDACT)
