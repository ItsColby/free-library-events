"""Home Assistant integration tests for Free Library Events."""

from __future__ import annotations

from datetime import date, time, timedelta
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import pytest

    from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResultType
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from pytest_homeassistant_custom_component.common import MockConfigEntry
except ModuleNotFoundError as err:  # pragma: no cover - local non-HA test env
    raise unittest.SkipTest(f"Home Assistant test harness unavailable: {err}") from err

from custom_components.free_library_events.api import (  # noqa: E402
    BranchFeed,
    LibraryApiError,
)
from custom_components.free_library_events.config import (  # noqa: E402
    normalize_config,
)
from custom_components.free_library_events.const import (  # noqa: E402
    ATTR_FORCE_REFRESH,
    ATTR_REFERENCE_DATE,
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_INCLUDE_INDEPENDENCE,
    CONF_INCLUDE_SANTORE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_RENDER_DIGEST,
)
from custom_components.free_library_events.coordinator import (  # noqa: E402
    LibraryDataCoordinator,
)
from custom_components.free_library_events.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)
from custom_components.free_library_events.digest import (  # noqa: E402
    BRANCHES,
    Event,
)


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

USER_INPUT = {
    CONF_CHILD_NAME: "Avery",
    CONF_BIRTH_DATE: "2025-01-15",
    CONF_INCLUDE_SANTORE: True,
    CONF_INCLUDE_INDEPENDENCE: True,
    CONF_FILTER_MODE: "Recommended",
    CONF_CALENDAR_DURATION: 60,
    CONF_SCAN_INTERVAL: 21600,
}


async def test_user_flow_creates_single_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    with patch(
        "custom_components.free_library_events.async_setup_entry",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            USER_INPUT,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Free Library Events"
    assert result["data"] == USER_INPUT


async def test_user_flow_rejects_duplicate_entry(hass: HomeAssistant) -> None:
    _entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


def test_normalize_config_enforces_non_ui_bounds() -> None:
    with pytest.raises(ValueError, match="invalid_calendar_duration"):
        normalize_config(USER_INPUT | {CONF_CALENDAR_DURATION: 5})
    with pytest.raises(ValueError, match="invalid_scan_interval"):
        normalize_config(USER_INPUT | {CONF_SCAN_INTERVAL: 30})


async def test_setup_entities_action_and_redacted_diagnostics(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    async def fetch(branch):
        event = Event(
            title="Baby Storytime",
            event_date=date(2026, 7, 22),
            start_time=time(10, 30),
            description="Stories and songs for babies with caregivers.",
            link=f"https://example.test/events/{branch.code.lower()}-1001",
            image_url="",
            branch=branch,
        )
        return BranchFeed(events=(event,), source_count=1)

    with patch(
        "custom_components.free_library_events.api.LibraryClient.async_fetch_branch",
        side_effect=fetch,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.title == "Free Library Events"
    registry_entries = [
        item
        for item in er.async_get(hass).entities.values()
        if item.config_entry_id == entry.entry_id and item.platform == DOMAIN
    ]
    assert {item.domain for item in registry_entries} == {
        "button",
        "calendar",
        "sensor",
    }
    assert (
        next(item.entity_id for item in registry_entries if item.domain == "calendar")
        == "calendar.free_library_events_calendar"
    )
    assert hass.services.has_service(DOMAIN, SERVICE_RENDER_DIGEST)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_RENDER_DIGEST,
        {
            ATTR_FORCE_REFRESH: False,
            ATTR_REFERENCE_DATE: date(2026, 7, 17),
        },
        blocking=True,
        return_response=True,
    )
    assert response["metadata"]["included_count"] == 2
    assert "Avery" in response["subject"]

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "Avery" not in repr(diagnostics)
    assert "2025-01-15" not in repr(diagnostics)
    assert list(diagnostics["sources"]) == [
        "Charles Santore Library",
        "Independence Library",
    ]


async def test_coordinator_retains_partial_source_success(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    success = BranchFeed(
        events=(),
        source_count=3,
    )
    client = types.SimpleNamespace(
        async_fetch_branch=AsyncMock(
            side_effect=[success, LibraryApiError("source unavailable")]
        )
    )
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        tuple(BRANCHES.values()),
        timedelta(hours=6),
    )
    data = await coordinator._async_update_data()
    assert data.source_counts == {"SWK": 3}
    assert data.source_errors == {"IND": "source unavailable"}


async def test_coordinator_rejects_complete_source_failure(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    client = types.SimpleNamespace(
        async_fetch_branch=AsyncMock(side_effect=LibraryApiError("offline"))
    )
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        tuple(BRANCHES.values()),
        timedelta(hours=6),
    )
    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator._async_update_data()


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Legacy child-specific title",
        unique_id=DOMAIN,
        data=USER_INPUT,
    )
