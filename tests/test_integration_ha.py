"""Home Assistant integration tests for Free Library Events."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, PropertyMock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aiohttp
import pytest
from homeassistant.components.smtp.helpers import _build_html_msg
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, is_callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.free_library_events import async_migrate_entry
from custom_components.free_library_events.api import (
    MAX_RSS_REQUEST_CONCURRENCY,
    MAX_RSS_RESPONSE_BYTES,
    OFFICIAL_EVENT_TYPES,
    SOURCE_ERROR_EXPANSION_TIMEOUT,
    SOURCE_ERROR_REQUEST_FAILED,
    SOURCE_ERROR_RESPONSE_TOO_LARGE,
    SOURCE_ERROR_UNEXPECTED,
    SOURCE_ERROR_UNSAFE_REDIRECT,
    TYPE_SHARD_BLOCKER_CAPPED,
    TYPE_SHARD_BLOCKER_MISSING_BOUNDARY,
    TYPE_SHARD_BLOCKER_PARSE_INCOMPLETE,
    TYPE_SHARD_BLOCKER_UNORDERED,
    BranchFeed,
    LibraryApiError,
    LibraryClient,
    TypeShardBlocker,
)
from custom_components.free_library_events.button import LibraryRefreshButton
from custom_components.free_library_events.calendar import LibraryCalendar
from custom_components.free_library_events.calendar_data import (
    build_calendar_items,
)
from custom_components.free_library_events.config import (
    LEGACY_BRANCH_CONFIG_KEYS,
    normalize_config,
    normalize_options,
    normalize_profile,
    selected_branches,
)
from custom_components.free_library_events.config_flow import (
    FreeLibraryEventsConfigFlow,
)
from custom_components.free_library_events.const import (
    ATTR_EMBED_IMAGES,
    ATTR_FORCE_REFRESH,
    CONF_BIRTH_DATE,
    CONF_BRANCHES,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_INCLUDE_INDEPENDENCE,
    CONF_INCLUDE_PARKWAY_CENTRAL,
    CONF_INCLUDE_PCI,
    CONF_INCLUDE_SANTORE,
    CONF_PUBLISH_WEBCAL,
    CONF_SCAN_INTERVAL,
    CONF_WEBCAL_NAME,
    CONF_WEBCAL_TOKEN,
    DOMAIN,
    SERVICE_RENDER_DIGEST,
)
from custom_components.free_library_events.coordinator import (
    MAX_TYPE_EXPANSIONS_PER_REFRESH,
    LibraryData,
    LibraryDataCoordinator,
    source_expansion_details,
    source_keys_for_window,
    supplemental_coverage,
    type_expansion_source_keys,
)
from custom_components.free_library_events.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.free_library_events.digest import (
    BRANCHES,
    DescriptionLink,
    Event,
    event_identity,
)
from custom_components.free_library_events.email_images import (
    EMAIL_IMAGE_DIRECTORY,
    DownloadedImage,
    ImageDownloadBatch,
    StoredImageBundle,
    remove_stored_image_run,
    store_downloaded_images,
)
from custom_components.free_library_events.sensor import (
    LibraryStatusSensor,
    _next_projection_deadline,
)
from custom_components.free_library_events.webcal import (
    WEBCAL_PATH,
    render_icalendar,
    webcal_subscription_urls,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

LOCAL_TIME_ZONE = ZoneInfo("America/New_York")

USER_INPUT = {
    CONF_CHILD_NAME: "Avery",
    CONF_BIRTH_DATE: "2025-01-15",
    CONF_INCLUDE_SANTORE: True,
    CONF_INCLUDE_INDEPENDENCE: True,
    CONF_INCLUDE_PARKWAY_CENTRAL: True,
    CONF_INCLUDE_PCI: True,
    CONF_FILTER_MODE: "Recommended",
    CONF_CALENDAR_DURATION: 60,
    CONF_SCAN_INTERVAL: 21600,
}

PROFILE_INPUT = {
    CONF_CHILD_NAME: "Avery",
    CONF_BIRTH_DATE: "2025-01-15",
    CONF_BRANCHES: ["SWK", "CEN"],
}

PROFILE_DATA = PROFILE_INPUT | {
    CONF_INCLUDE_SANTORE: True,
    CONF_INCLUDE_INDEPENDENCE: False,
    CONF_INCLUDE_PARKWAY_CENTRAL: True,
    CONF_INCLUDE_PCI: False,
}

BEHAVIOR_INPUT = {
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
            PROFILE_INPUT,
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Free Library Events"
    assert result["data"] == PROFILE_DATA


async def test_reconfigure_flow_updates_profile_data_only(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data={**PROFILE_DATA, "future_profile": {"enabled": True}},
        options=BEHAVIOR_INPUT,
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    updated_profile = PROFILE_INPUT | {
        CONF_CHILD_NAME: "Jordan",
        CONF_BRANCHES: ["IND", "PCI"],
    }
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], updated_profile
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == updated_profile | {
        CONF_INCLUDE_SANTORE: False,
        CONF_INCLUDE_INDEPENDENCE: True,
        CONF_INCLUDE_PARKWAY_CENTRAL: False,
        CONF_INCLUDE_PCI: True,
        "future_profile": {"enabled": True},
    }
    assert entry.options == BEHAVIOR_INPUT


async def test_reconfigure_flow_does_not_reload_unchanged_profile(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options=BEHAVIOR_INPUT,
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    with patch.object(hass.config_entries, "async_schedule_reload") as schedule_reload:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], PROFILE_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == PROFILE_DATA
    schedule_reload.assert_not_called()


async def test_user_flow_rejects_duplicate_entry(hass: HomeAssistant) -> None:
    _entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_behavior_options_do_not_depend_on_deprecated_advanced_mode(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options=BEHAVIOR_INPUT,
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(
        "homeassistant.data_entry_flow.FlowHandler.show_advanced_options",
        new_callable=PropertyMock,
        side_effect=AssertionError("deprecated advanced-mode property accessed"),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "behavior"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "behavior"
    assert {marker.schema for marker in result["data_schema"].schema} == {
        CONF_FILTER_MODE,
        CONF_CALENDAR_DURATION,
        CONF_SCAN_INTERVAL,
    }
    assert is_callback(FreeLibraryEventsConfigFlow.async_get_options_flow)


async def test_options_flow_enables_and_rotates_webcal_feed(
    hass: HomeAssistant,
) -> None:
    future_option = {"future_behavior": {"enabled": True}}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options={**BEHAVIOR_INPUT, **future_option},
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    hass.config.external_url = "https://ha.example.test"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == ["behavior", "webcal"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "webcal"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webcal"

    first_token = "first-synthetic-subscription-token"
    with patch(
        "custom_components.free_library_events.config_flow.token_urlsafe",
        return_value=first_token,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_PUBLISH_WEBCAL: True,
                CONF_WEBCAL_NAME: "Neighborhood Library Events",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webcal_url"
    assert result["description_placeholders"] == {
        "http_url": (
            "https://ha.example.test/api/free_library_events/calendar/"
            f"{first_token}.ics"
        ),
        "webcal_url": (
            "webcal://ha.example.test/api/free_library_events/calendar/"
            f"{first_token}.ics"
        ),
        "url_scope": "Home Assistant external or cloud URL configured",
    }

    entry.runtime_data = Mock(source_result_count=1)
    entry.runtime_data.source_result_count = 2
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PUBLISH_WEBCAL] is True
    assert entry.options[CONF_WEBCAL_TOKEN] == first_token
    assert entry.options[CONF_WEBCAL_NAME] == "Neighborhood Library Events"
    assert "regenerate_webcal_token" not in entry.options
    assert entry.options["future_behavior"] == future_option["future_behavior"]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["behavior", "webcal", "regenerate_webcal"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "regenerate_webcal"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "regenerate_webcal"

    second_token = "second-synthetic-subscription-token"
    with patch(
        "custom_components.free_library_events.config_flow.token_urlsafe",
        return_value=second_token,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {},
        )
    assert second_token in result["description_placeholders"]["webcal_url"]
    assert first_token not in result["description_placeholders"]["webcal_url"]
    assert entry.options[CONF_WEBCAL_TOKEN] == first_token
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_WEBCAL_TOKEN] == second_token
    assert entry.options["future_behavior"] == future_option["future_behavior"]


async def test_webcal_preview_rejects_competing_options_update(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options=BEHAVIOR_INPUT,
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    hass.config.external_url = "https://ha.example.test"

    webcal_result = await hass.config_entries.options.async_init(entry.entry_id)
    webcal_result = await hass.config_entries.options.async_configure(
        webcal_result["flow_id"], {"next_step_id": "webcal"}
    )
    with patch(
        "custom_components.free_library_events.config_flow.token_urlsafe",
        return_value="pending-synthetic-subscription-token",
    ):
        webcal_result = await hass.config_entries.options.async_configure(
            webcal_result["flow_id"],
            {
                CONF_PUBLISH_WEBCAL: True,
                CONF_WEBCAL_NAME: "Pending Library Events",
            },
        )
    assert webcal_result["step_id"] == "webcal_url"

    behavior_result = await hass.config_entries.options.async_init(entry.entry_id)
    behavior_result = await hass.config_entries.options.async_configure(
        behavior_result["flow_id"], {"next_step_id": "behavior"}
    )
    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as async_reload:
        behavior_result = await hass.config_entries.options.async_configure(
            behavior_result["flow_id"], {CONF_FILTER_MODE: "Strict"}
        )
        webcal_result = await hass.config_entries.options.async_configure(
            webcal_result["flow_id"], {}
        )

    assert behavior_result["type"] is FlowResultType.CREATE_ENTRY
    assert webcal_result["type"] is FlowResultType.ABORT
    assert webcal_result["reason"] == "options_changed"
    assert entry.options[CONF_FILTER_MODE] == "Strict"
    assert CONF_WEBCAL_TOKEN not in entry.options
    assert async_reload.await_count == 1


async def test_webcal_preview_rejects_external_profile_update(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options=BEHAVIOR_INPUT,
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    hass.config.external_url = "https://ha.example.test"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "webcal"}
    )
    with patch(
        "custom_components.free_library_events.config_flow.token_urlsafe",
        return_value="pending-synthetic-subscription-token",
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_PUBLISH_WEBCAL: True,
                CONF_WEBCAL_NAME: "Pending Library Events",
            },
        )
    updated_data = {**entry.data, CONF_CHILD_NAME: "Jordan"}
    hass.config_entries.async_update_entry(entry, data=updated_data)

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as async_reload:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "options_changed"
    assert entry.data == updated_data
    assert entry.options == BEHAVIOR_INPUT
    async_reload.assert_not_awaited()


async def test_options_flow_preserves_unrecognized_options(
    hass: HomeAssistant,
) -> None:
    future_option = {"future_behavior": {"enabled": True}}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options={**BEHAVIOR_INPUT, **future_option},
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "behavior"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FILTER_MODE: "Strict"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FILTER_MODE] == "Strict"
    assert entry.options["future_behavior"] == future_option["future_behavior"]


async def test_options_flow_disables_webcal_and_removes_token(
    hass: HomeAssistant,
) -> None:
    old_token = "disabled-synthetic-subscription-token"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options={
            **BEHAVIOR_INPUT,
            CONF_PUBLISH_WEBCAL: True,
            CONF_WEBCAL_TOKEN: old_token,
            CONF_WEBCAL_NAME: "Free Library Events",
            "future_behavior": {"enabled": True},
        },
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "webcal"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PUBLISH_WEBCAL: False,
            CONF_WEBCAL_NAME: "Free Library Events",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PUBLISH_WEBCAL] is False
    assert CONF_WEBCAL_TOKEN not in entry.options
    assert entry.options["future_behavior"] == {"enabled": True}


async def test_options_flow_does_not_save_webcal_without_a_home_assistant_url(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options=BEHAVIOR_INPUT,
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "webcal"}
    )
    with patch(
        "custom_components.free_library_events.webcal.get_url",
        side_effect=NoURLAvailableError,
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_PUBLISH_WEBCAL: True,
                CONF_WEBCAL_NAME: "Neighborhood Library Events",
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "webcal"
    assert result["errors"] == {"base": "webcal_url_unavailable"}
    assert CONF_WEBCAL_TOKEN not in entry.options


async def test_options_flow_updates_behavior_without_profile_data(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=PROFILE_DATA,
        options=BEHAVIOR_INPUT,
        version=1,
        minor_version=2,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "behavior"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FILTER_MODE: "Strict"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data == PROFILE_DATA
    assert entry.options[CONF_FILTER_MODE] == "Strict"
    assert entry.options[CONF_CALENDAR_DURATION] == 60
    assert entry.options[CONF_SCAN_INTERVAL] == 21600


async def test_manual_refresh_button_remains_available_and_reports_result(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        types.SimpleNamespace(),
        (BRANCHES["SWK"],),
        date(2025, 1, 15),
        timedelta(hours=6),
    )
    coordinator.async_request_refresh = AsyncMock()
    coordinator.last_update_success = False
    button = LibraryRefreshButton(coordinator)

    assert button.available

    with pytest.raises(HomeAssistantError) as failure:
        await button.async_press()

    assert failure.value.translation_domain == DOMAIN
    assert failure.value.translation_key == "manual_refresh_failed"
    assert coordinator.async_request_refresh.await_count == 1
    assert button.available

    coordinator.last_update_success = True
    await button.async_press()
    assert coordinator.async_request_refresh.await_count == 2
    assert button.available


def test_normalize_config_enforces_non_ui_bounds() -> None:
    with pytest.raises(ValueError, match="invalid_calendar_duration"):
        normalize_config(USER_INPUT | {CONF_CALENDAR_DURATION: 5})
    with pytest.raises(ValueError, match="invalid_scan_interval"):
        normalize_config(USER_INPUT | {CONF_SCAN_INTERVAL: 30})


def test_profile_and_webcal_validation_reject_unknown_or_unsafe_values() -> None:
    with pytest.raises(ValueError, match="child_name_required"):
        normalize_profile(
            {
                key: value
                for key, value in PROFILE_INPUT.items()
                if key != CONF_CHILD_NAME
            }
        )
    with pytest.raises(ValueError, match="invalid_branches"):
        normalize_profile(PROFILE_INPUT | {CONF_BRANCHES: ["SWK", "UNKNOWN"]})
    with pytest.raises(ValueError, match="branch_required"):
        normalize_profile(PROFILE_INPUT | {CONF_BRANCHES: []})
    with pytest.raises(ValueError, match="invalid_webcal_name"):
        normalize_options(BEHAVIOR_INPUT | {CONF_WEBCAL_NAME: " \n "})
    with pytest.raises(TypeError, match="invalid_webcal_name"):
        normalize_options(BEHAVIOR_INPUT | {CONF_WEBCAL_NAME: None})

    private_detail = "synthetic-private-birth-date"
    with pytest.raises(ValueError, match="invalid_birth_date") as invalid_birth_date:
        normalize_profile(PROFILE_INPUT | {CONF_BIRTH_DATE: private_detail})
    assert invalid_birth_date.value.__cause__ is None
    assert private_detail not in repr(invalid_birth_date.value)


def test_normalize_config_coerces_non_ui_boolean_strings() -> None:
    disabled = dict.fromkeys(
        (
            CONF_INCLUDE_SANTORE,
            CONF_INCLUDE_INDEPENDENCE,
            CONF_INCLUDE_PARKWAY_CENTRAL,
            CONF_INCLUDE_PCI,
        ),
        "false",
    )

    with pytest.raises(ValueError, match="branch_required"):
        normalize_config(USER_INPUT | disabled)


def test_normalize_config_rejects_non_string_child_name() -> None:
    with pytest.raises(TypeError, match="invalid_child_name"):
        normalize_config(USER_INPUT | {CONF_CHILD_NAME: None})


def test_all_sources_default_on_for_legacy_and_new_entries() -> None:
    legacy_input = {
        key: value
        for key, value in USER_INPUT.items()
        if key not in {CONF_INCLUDE_PARKWAY_CENTRAL, CONF_INCLUDE_PCI}
    }
    legacy_config = normalize_config(legacy_input)
    assert legacy_config[CONF_BRANCHES] == ["SWK", "IND", "CEN", "PCI"]
    assert [branch.code for branch in selected_branches(legacy_config)] == [
        "SWK",
        "IND",
        "CEN",
        "PCI",
    ]


async def test_version_one_entry_migrates_profile_and_behavior_without_token_leak(
    hass: HomeAssistant,
) -> None:
    token = "synthetic-migration-subscription-token"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=USER_INPUT | {"future_data": {"version": 2}},
        options=USER_INPUT
        | {
            CONF_CHILD_NAME: "Jordan",
            CONF_INCLUDE_PCI: False,
            CONF_FILTER_MODE: "Strict",
            CONF_PUBLISH_WEBCAL: True,
            CONF_WEBCAL_TOKEN: token,
            "future_options": {"version": 2},
        },
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 1
    assert entry.minor_version == 2
    assert entry.data == {
        CONF_CHILD_NAME: "Jordan",
        CONF_BIRTH_DATE: "2025-01-15",
        CONF_BRANCHES: ["SWK", "IND", "CEN"],
        CONF_INCLUDE_SANTORE: True,
        CONF_INCLUDE_INDEPENDENCE: True,
        CONF_INCLUDE_PARKWAY_CENTRAL: True,
        CONF_INCLUDE_PCI: False,
        "future_data": {"version": 2},
    }
    assert entry.options[CONF_FILTER_MODE] == "Strict"
    assert entry.options[CONF_WEBCAL_TOKEN] == token
    assert entry.options["future_options"] == {"version": 2}
    assert CONF_CHILD_NAME not in entry.options
    assert CONF_BIRTH_DATE not in entry.options
    assert token not in repr(entry.data)
    assert [
        branch_code
        for config_key, branch_code in LEGACY_BRANCH_CONFIG_KEYS
        if entry.data[config_key]
    ] == ["SWK", "IND", "CEN"]


def test_status_projection_deadline_uses_local_tuesday_across_dst() -> None:
    spring_now = datetime(2026, 3, 3, tzinfo=LOCAL_TIME_ZONE)
    spring_deadline = _next_projection_deadline(spring_now, LOCAL_TIME_ZONE)
    assert spring_deadline == datetime(2026, 3, 10, tzinfo=LOCAL_TIME_ZONE)
    assert spring_deadline.astimezone(ZoneInfo("UTC")) - spring_now.astimezone(
        ZoneInfo("UTC")
    ) == timedelta(hours=167)

    fall_now = datetime(2026, 10, 27, tzinfo=LOCAL_TIME_ZONE)
    fall_deadline = _next_projection_deadline(fall_now, LOCAL_TIME_ZONE)
    assert fall_deadline == datetime(2026, 11, 3, tzinfo=LOCAL_TIME_ZONE)
    assert fall_deadline.astimezone(ZoneInfo("UTC")) - fall_now.astimezone(
        ZoneInfo("UTC")
    ) == timedelta(hours=169)


async def test_status_projection_advances_at_tuesday_without_source_io(
    hass: HomeAssistant,
) -> None:
    await hass.config.async_set_time_zone("America/New_York")
    entry = _entry()
    entry.add_to_hass(hass)
    event = Event(
        title="Monday-window storytime",
        event_date=date(2026, 7, 22),
        start_time=time(10, 30),
        description="Stories and songs for babies with caregivers.",
        link="https://example.test/events/monday-window-storytime",
        image_url="",
        branch=BRANCHES["CEN"],
        age_categories=("Baby",),
    )

    async def fetch_feed(branch, age_category, _coverage_end=None):
        return BranchFeed(
            events=(
                (replace(event, branch=branch, age_categories=(age_category,)),)
                if branch.code == "CEN"
                else ()
            ),
            age_category=age_category,
            source_count=10,
            parsed_count=10,
            last_event_date=event.event_date,
            ordered=True,
            type_shards_queried=len(OFFICIAL_EVENT_TYPES),
            expanded_through=date(2026, 7, 26),
        )

    fetch_mock = AsyncMock(side_effect=fetch_feed)
    monday = datetime(2026, 7, 20, 23, 59, tzinfo=LOCAL_TIME_ZONE)
    scheduled: list[tuple[Callable[[datetime], None], datetime, Mock]] = []

    def track_projection(
        _hass: HomeAssistant,
        action: Callable[[datetime], None],
        deadline: datetime,
    ) -> Mock:
        cancel = Mock()
        scheduled.append((action, deadline, cancel))
        return cancel

    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            new=fetch_mock,
        ),
        patch(
            "custom_components.free_library_events.sensor.async_track_point_in_time",
            side_effect=track_projection,
        ),
        patch("homeassistant.util.dt.now", return_value=monday),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        initial = hass.states.get("sensor.free_library_events_status")
        assert initial is not None
        assert initial.state == "ok"
        assert initial.attributes["next_week_events"] == 1
        assert initial.attributes["current_age_coverage_complete"] is True
        cached_data = entry.runtime_data.data
        initial_fetch_count = fetch_mock.await_count
        assert len(scheduled) == 1
        assert scheduled[0][1] == datetime(2026, 7, 21, tzinfo=LOCAL_TIME_ZONE)

        scheduled[0][0](datetime(2026, 7, 21, tzinfo=LOCAL_TIME_ZONE))
        await hass.async_block_till_done()

    advanced = hass.states.get("sensor.free_library_events_status")
    assert advanced is not None
    assert advanced.state == "partial"
    assert advanced.attributes["next_week_events"] == 0
    assert advanced.attributes["current_age_coverage_complete"] is False
    assert advanced.attributes["current_age_coverage_warnings"]
    assert entry.runtime_data.data is cached_data
    assert fetch_mock.await_count == initial_fetch_count
    assert len(scheduled) == 2
    assert scheduled[1][1] == datetime(2026, 7, 28, tzinfo=LOCAL_TIME_ZONE)


async def test_unchanged_status_projection_skips_state_write_and_source_io(
    hass: HomeAssistant,
) -> None:
    await hass.config.async_set_time_zone("America/New_York")
    entry = _entry()
    entry.add_to_hass(hass)
    fetch_mock = AsyncMock(
        side_effect=lambda _branch, age_category, _coverage_end=None: BranchFeed(
            events=(),
            age_category=age_category,
            source_count=0,
            parsed_count=0,
            last_event_date=None,
            ordered=True,
        )
    )
    monday = datetime(2026, 7, 20, 23, 59, tzinfo=LOCAL_TIME_ZONE)
    scheduled: list[tuple[Callable[[datetime], None], datetime, Mock]] = []

    def track_projection(
        _hass: HomeAssistant,
        action: Callable[[datetime], None],
        deadline: datetime,
    ) -> Mock:
        cancel = Mock()
        scheduled.append((action, deadline, cancel))
        return cancel

    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            new=fetch_mock,
        ),
        patch(
            "custom_components.free_library_events.sensor.async_track_point_in_time",
            side_effect=track_projection,
        ),
        patch("homeassistant.util.dt.now", return_value=monday),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(scheduled) == 1
        initial_fetch_count = fetch_mock.await_count
        with patch.object(
            LibraryStatusSensor, "async_write_ha_state", autospec=True
        ) as write_state:
            scheduled[0][0](datetime(2026, 7, 21, tzinfo=LOCAL_TIME_ZONE))

        write_state.assert_not_called()
        assert len(scheduled) == 2
        assert scheduled[1][1] == datetime(2026, 7, 28, tzinfo=LOCAL_TIME_ZONE)
        assert fetch_mock.await_count == initial_fetch_count
        unchanged = hass.states.get("sensor.free_library_events_status")
        assert unchanged is not None
        assert unchanged.state == "ok"
        assert unchanged.attributes["next_week_events"] == 0
        assert await hass.config_entries.async_unload(entry.entry_id)

    scheduled[1][2].assert_called_once_with()


async def test_status_projection_reschedules_for_runtime_timezone_change(
    hass: HomeAssistant,
) -> None:
    await hass.config.async_set_time_zone("America/New_York")
    entry = _entry()
    entry.add_to_hass(hass)
    fetch_mock = AsyncMock(
        side_effect=lambda _branch, age_category, _coverage_end=None: BranchFeed(
            events=(),
            age_category=age_category,
            source_count=0,
            parsed_count=0,
            last_event_date=None,
            ordered=True,
        )
    )
    scheduled: list[tuple[object, datetime, Mock]] = []

    def track_projection(_hass, action, deadline):
        cancel = Mock()
        scheduled.append((action, deadline, cancel))
        return cancel

    utc_now = datetime(2026, 7, 20, 16, tzinfo=ZoneInfo("UTC"))

    def local_now(time_zone=None):
        return utc_now.astimezone(time_zone) if time_zone is not None else utc_now

    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            new=fetch_mock,
        ),
        patch(
            "custom_components.free_library_events.sensor.async_track_point_in_time",
            side_effect=track_projection,
        ),
        patch("homeassistant.util.dt.now", side_effect=local_now),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(scheduled) == 1
        assert scheduled[0][1] == datetime(2026, 7, 21, tzinfo=LOCAL_TIME_ZONE)
        initial_fetch_count = fetch_mock.await_count

        with patch.object(
            LibraryStatusSensor, "async_write_ha_state", autospec=True
        ) as write_state:
            await hass.config.async_update(time_zone="America/Los_Angeles")
            await hass.async_block_till_done()

            write_state.assert_not_called()

        assert len(scheduled) == 2
        scheduled[0][2].assert_called_once_with()
        assert scheduled[1][1] == datetime(
            2026, 7, 21, tzinfo=ZoneInfo("America/Los_Angeles")
        )
        assert fetch_mock.await_count == initial_fetch_count
        assert await hass.config_entries.async_unload(entry.entry_id)
        scheduled[1][2].assert_called_once_with()

        await hass.config.async_update(time_zone="America/New_York")
        await hass.async_block_till_done()

    assert len(scheduled) == 2


async def test_status_projection_reschedules_on_failure_recovery_and_unload(
    hass: HomeAssistant,
) -> None:
    await hass.config.async_set_time_zone("America/New_York")
    entry = _entry()
    entry.add_to_hass(hass)
    fetch_mock = AsyncMock(
        side_effect=lambda _branch, age_category, _coverage_end=None: BranchFeed(
            events=(),
            age_category=age_category,
            source_count=0,
            parsed_count=0,
            last_event_date=None,
            ordered=True,
        )
    )
    scheduled: list[tuple[object, datetime, Mock]] = []

    def track_projection(_hass, action, deadline):
        cancel = Mock()
        scheduled.append((action, deadline, cancel))
        return cancel

    monday = datetime(2026, 7, 20, 12, tzinfo=LOCAL_TIME_ZONE)
    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            new=fetch_mock,
        ),
        patch(
            "custom_components.free_library_events.sensor.async_track_point_in_time",
            side_effect=track_projection,
        ),
        patch("homeassistant.util.dt.now", return_value=monday),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(scheduled) == 1
        assert scheduled[0][1] == datetime(2026, 7, 21, tzinfo=LOCAL_TIME_ZONE)

        coordinator = entry.runtime_data
        assert coordinator.data is not None
        original_data = coordinator.data
        coordinator.async_set_update_error(
            UpdateFailed("synthetic source update failure")
        )
        await hass.async_block_till_done()

        failed_button = hass.states.get("button.free_library_events_refresh_events")
        assert failed_button is not None
        assert failed_button.state != STATE_UNAVAILABLE
        coordinator.async_request_refresh = AsyncMock()
        with pytest.raises(HomeAssistantError) as failure:
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.free_library_events_refresh_events"},
                blocking=True,
            )
        assert failure.value.translation_domain == DOMAIN
        assert failure.value.translation_key == "manual_refresh_failed"
        assert coordinator.async_request_refresh.await_count == 1

        failed = hass.states.get("sensor.free_library_events_status")
        assert failed is not None
        assert failed.state == "error"
        assert coordinator.data is original_data
        assert len(scheduled) == 2
        scheduled[0][2].assert_called_once_with()

        coordinator.async_set_updated_data(
            replace(
                original_data,
                fetched_at=original_data.fetched_at + timedelta(seconds=1),
            )
        )
        await hass.async_block_till_done()

        recovered = hass.states.get("sensor.free_library_events_status")
        assert recovered is not None
        assert recovered.state == "ok"
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.free_library_events_refresh_events"},
            blocking=True,
        )
        assert coordinator.async_request_refresh.await_count == 2
        recovered_button = hass.states.get("button.free_library_events_refresh_events")
        assert recovered_button is not None
        assert recovered_button.state != STATE_UNAVAILABLE
        assert len(scheduled) == 3
        scheduled[1][2].assert_called_once_with()
        assert scheduled[2][1] == datetime(2026, 7, 21, tzinfo=LOCAL_TIME_ZONE)
        assert await hass.config_entries.async_unload(entry.entry_id)

    scheduled[2][2].assert_called_once_with()


async def test_setup_entities_action_and_redacted_diagnostics(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    async def fetch_filtered(branch, age_category, _coverage_end=None):
        event = Event(
            title="Baby Storytime",
            event_date=date(2026, 7, 22),
            start_time=time(10, 30),
            description="Stories and songs for babies with caregivers.",
            link=f"https://example.test/events/{branch.code.lower()}-1001",
            image_url="https://libwww.freelibrary.org/images/storytime.png",
            branch=branch,
            age_categories=(age_category,) if age_category else (),
            end_at=datetime(2026, 7, 22, 12, 0, tzinfo=LOCAL_TIME_ZONE),
            description_links=(
                DescriptionLink("Early literacy", "https://example.test/literacy"),
            ),
            room="Storyhour Room",
        )
        return BranchFeed(
            events=(event,),
            age_category=age_category,
            source_count=1,
            parsed_count=1,
            last_event_date=event.event_date,
            ordered=True,
        )

    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            side_effect=fetch_filtered,
        ),
        patch(
            "homeassistant.util.dt.now",
            return_value=datetime(2026, 7, 17, 12, tzinfo=LOCAL_TIME_ZONE),
        ),
        patch(
            "custom_components.free_library_events.sensor.async_track_point_in_time",
            return_value=Mock(),
        ),
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
    calendar_state = hass.states.get("calendar.free_library_events_calendar")
    assert calendar_state is not None
    assert "Avery" not in calendar_state.attributes["description"]
    assert "Official details:" in calendar_state.attributes["description"]
    assert (
        "Related: Early literacy: https://example.test/literacy"
        in (calendar_state.attributes["description"])
    )
    assert "End time not published" not in calendar_state.attributes["description"]
    assert datetime.fromisoformat(
        calendar_state.attributes["end_time"]
    ) - datetime.fromisoformat(calendar_state.attributes["start_time"]) == timedelta(
        minutes=90
    )
    assert calendar_state.attributes["location"].startswith("Charles Santore Library")
    assert "Storyhour Room" in calendar_state.attributes["location"]
    status_state = hass.states.get("sensor.free_library_events_status")
    assert status_state is not None
    assert status_state.state == "ok"
    assert status_state.attributes["device_class"] == "enum"
    assert status_state.attributes["options"] == ["ok", "limited", "partial", "error"]
    assert status_state.attributes["next_week_events"] == 4
    assert status_state.attributes["current_age_coverage_complete"] is True
    assert status_state.attributes["supplemental_age_coverage_complete"] is True
    assert status_state.attributes["expanded_capped_sources"] == {}
    assert status_state.attributes["last_attempt_requested_sources"] == 20
    assert status_state.attributes["last_attempt_successful_sources"] == 20
    assert status_state.attributes["last_attempt_failed_sources"] == 0
    assert status_state.attributes["last_attempt_retryable_failures"] == 0
    assert status_state.attributes["last_attempt_error_categories"] == {}
    assert status_state.attributes["expedited_retry_scheduled"] is False
    assert status_state.attributes["cached_events_by_branch"] == {
        "Charles Santore Library": 1,
        "Independence Library": 1,
        "Parkway Central Library": 1,
        "Philadelphia City Institute": 1,
    }
    assert "matched_events" not in status_state.attributes
    assert "source_counts" not in status_state.attributes
    assert "coverage_complete" not in status_state.attributes
    assert hass.services.has_service(DOMAIN, SERVICE_RENDER_DIGEST)

    with patch(
        "custom_components.free_library_events.dt_util.now",
        return_value=datetime(2026, 7, 17, tzinfo=LOCAL_TIME_ZONE),
    ):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            {ATTR_FORCE_REFRESH: False},
            blocking=True,
            return_response=True,
        )
    assert response["metadata"]["included_count"] == 4
    assert response["metadata"]["expanded_capped_sources"] == {}
    assert response["metadata"]["fetched_at"] == status_state.attributes["last_refresh"]
    assert "Avery" in response["subject"]
    json.dumps(response)

    image_url = "https://libwww.freelibrary.org/images/storytime.png"
    image_path = Path(
        hass.config.media_dirs["local"],
        EMAIL_IMAGE_DIRECTORY,
        "run-0123456789abcdef0123456789abcdef",
        "event-01.png",
    )
    unused_image_url = "https://libwww.freelibrary.org/images/unused.png"
    unused_image_path = image_path.with_name("event-02.png")
    download_batch = ImageDownloadBatch(
        images=(
            DownloadedImage(image_url, b"image", ".png"),
            DownloadedImage(unused_image_url, b"unused", ".png"),
        ),
        requested_count=2,
        failure_count=0,
        failure_examples=(),
    )
    stored_bundle = StoredImageBundle(
        {
            image_url: "cid:event-01.png",
            unused_image_url: "cid:event-02.png",
        },
        (str(image_path), str(unused_image_path)),
        image_path.parent,
        {image_url: "hero", unused_image_url: "side"},
    )
    original_data = entry.runtime_data.data
    assert original_data is not None
    replacement_data = replace(
        original_data,
        events=(),
        fetched_at=original_data.fetched_at + timedelta(minutes=1),
    )

    async def download_while_snapshot_changes(*_args):
        entry.runtime_data.async_set_updated_data(replacement_data)
        return download_batch

    try:
        with (
            patch(
                "custom_components.free_library_events.async_download_event_images",
                side_effect=download_while_snapshot_changes,
            ),
            patch(
                "custom_components.free_library_events.store_downloaded_images",
                return_value=stored_bundle,
            ),
            patch("custom_components.free_library_events.purge_stale_image_runs"),
            patch("custom_components.free_library_events.async_call_later"),
            patch(
                "custom_components.free_library_events.dt_util.now",
                return_value=datetime(2026, 7, 17, tzinfo=LOCAL_TIME_ZONE),
            ),
        ):
            stable_snapshot = await hass.services.async_call(
                DOMAIN,
                SERVICE_RENDER_DIGEST,
                {ATTR_FORCE_REFRESH: False, ATTR_EMBED_IMAGES: True},
                blocking=True,
                return_response=True,
            )
    finally:
        entry.runtime_data.async_set_updated_data(original_data)
    assert stable_snapshot["metadata"]["included_count"] == 4
    assert stable_snapshot["metadata"]["fetched_at"] == (
        original_data.fetched_at.isoformat()
    )
    json.dumps(stable_snapshot)
    with (
        patch(
            "custom_components.free_library_events.async_download_event_images",
            new_callable=AsyncMock,
            return_value=download_batch,
        ),
        patch(
            "custom_components.free_library_events.store_downloaded_images",
            return_value=stored_bundle,
        ),
        patch("custom_components.free_library_events.purge_stale_image_runs"),
        patch("custom_components.free_library_events.async_call_later") as schedule,
        patch(
            "custom_components.free_library_events.dt_util.now",
            return_value=datetime(2026, 7, 17, tzinfo=LOCAL_TIME_ZONE),
        ),
    ):
        embedded = await hass.services.async_call(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            {ATTR_FORCE_REFRESH: False, ATTR_EMBED_IMAGES: True},
            blocking=True,
            return_response=True,
        )
    assert embedded["images"] == [str(image_path)]
    assert embedded["attachments"] == [
        {
            "media_source": {
                "media_content_id": (
                    "media-source://media_source/local/"
                    f"{EMAIL_IMAGE_DIRECTORY}/"
                    "run-0123456789abcdef0123456789abcdef/event-01.png"
                ),
                "media_content_type": "image/png",
            },
            "filename": "event-01.png",
            "content_id": "event-01.png",
        }
    ]
    assert embedded["metadata"]["embedded_image_count"] == 1
    assert embedded["metadata"]["smtp_attachment_count"] == 1
    assert embedded["metadata"]["image_download_count"] == 2
    assert embedded["metadata"]["image_download_failure_count"] == 0
    assert 'src="cid:event-01.png"' in embedded["html"]
    assert "cid:event-02.png" not in embedded["html"]
    json.dumps(embedded)
    assert 'class="event-hero-image-cell"' in embedded["html"]
    schedule.assert_called_once()

    with (
        patch(
            "custom_components.free_library_events.async_download_event_images",
            new_callable=AsyncMock,
            return_value=download_batch,
        ),
        patch(
            "custom_components.free_library_events.store_downloaded_images",
            side_effect=OSError("storage unavailable"),
        ),
        patch("custom_components.free_library_events.purge_stale_image_runs"),
        patch(
            "custom_components.free_library_events.dt_util.now",
            return_value=datetime(2026, 7, 17, tzinfo=LOCAL_TIME_ZONE),
        ),
    ):
        remote_fallback = await hass.services.async_call(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            {ATTR_FORCE_REFRESH: False, ATTR_EMBED_IMAGES: True},
            blocking=True,
            return_response=True,
        )
    assert remote_fallback["images"] == []
    assert remote_fallback["attachments"] == []
    assert remote_fallback["metadata"]["smtp_attachment_count"] == 0
    assert remote_fallback["metadata"]["image_download_failure_count"] == 2
    assert remote_fallback["metadata"]["image_download_failure_examples"] == [
        "Home Assistant could not store digest images"
    ]
    assert "storage unavailable" not in repr(remote_fallback)
    assert f'src="{image_url}"' in remote_fallback["html"]

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "Avery" not in repr(diagnostics)
    assert "2025-01-15" not in repr(diagnostics)
    assert list(diagnostics["sources"]) == [
        f"{branch.name} — {category}"
        for branch in BRANCHES.values()
        for category in ("Baby", "Toddler", "Preschool", "School Age", "Young Adult")
    ]
    assert diagnostics["last_attempt"]["requested_source_count"] == 20
    assert diagnostics["last_attempt"]["successful_source_count"] == 20
    assert diagnostics["last_attempt"]["failed_source_count"] == 0
    assert diagnostics["last_attempt"]["sources"] == {
        f"{branch.name} — {category}": {
            "available": True,
            "error_category": None,
        }
        for branch in BRANCHES.values()
        for category in ("Baby", "Toddler", "Preschool", "School Age", "Young Adult")
    }


@pytest.mark.parametrize("supersession", ("profile", "coordinator"))
async def test_render_digest_rejects_superseded_entry_during_refresh(
    hass: HomeAssistant, supersession: str
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    async def fetch_empty(_branch, age_category):
        return BranchFeed(
            events=(),
            age_category=age_category,
            source_count=0,
            parsed_count=0,
            last_event_date=None,
            ordered=True,
        )

    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            side_effect=fetch_empty,
        ),
        patch(
            "custom_components.free_library_events.sensor.async_track_point_in_time",
            return_value=Mock(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data

    async def refresh_while_entry_is_superseded() -> None:
        if supersession == "profile":
            hass.config_entries.async_update_entry(
                entry,
                data={**dict(entry.data), CONF_CHILD_NAME: "Jordan"},
            )
        else:
            entry.runtime_data = Mock()

    with (
        patch.object(
            coordinator,
            "async_request_refresh",
            side_effect=refresh_while_entry_is_superseded,
        ),
        pytest.raises(HomeAssistantError) as failure,
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            {ATTR_FORCE_REFRESH: True},
            blocking=True,
            return_response=True,
        )

    assert failure.value.translation_domain == DOMAIN
    assert failure.value.translation_key == "settings_changed_during_render"
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_stored_cid_images_match_home_assistant_smtp_mime_contract(
    hass: HomeAssistant,
    tmp_path: Path,
) -> None:
    source_url = "https://libwww.freelibrary.org/images/landscape.png"
    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1200).to_bytes(4, "big")
        + (600).to_bytes(4, "big")
        + b"rest"
    )
    batch = ImageDownloadBatch(
        images=(DownloadedImage(source_url, png, ".png", 1200, 600),),
        requested_count=1,
        failure_count=0,
        failure_examples=(),
    )
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    bundle = store_downloaded_images(tmp_path / EMAIL_IMAGE_DIRECTORY, batch)
    try:
        cid = bundle.source_url_to_cid[source_url]
        message = _build_html_msg(
            hass,
            "Plain fallback",
            f'<html><body><img src="{cid}" alt="Event details"></body></html>',
            list(bundle.paths),
        )
        parts = list(message.walk())

        image_part = next(
            part for part in parts if part.get_content_maintype() == "image"
        )
        html_part = next(
            part for part in parts if part.get_content_type() == "text/html"
        )
        expected_content_id = f"<{Path(bundle.paths[0]).name}>"
        assert image_part["Content-ID"] == expected_content_id
        assert cid in html_part.get_payload(decode=True).decode("utf-8")
    finally:
        assert bundle.run_directory is not None
        remove_stored_image_run(bundle.run_directory)


def test_calendar_keeps_recurring_series_occurrences_distinct() -> None:
    first = Event(
        title="Weekly Storytime",
        event_date=date(2026, 7, 20),
        start_time=time(10, 30),
        description="Stories and songs.",
        link="https://example.test/events/weekly-series",
        image_url="",
        branch=BRANCHES["IND"],
        age_categories=("Baby",),
    )
    second = Event(
        title=first.title,
        event_date=date(2026, 7, 27),
        start_time=first.start_time,
        description=first.description,
        link=first.link,
        image_url="",
        branch=first.branch,
        age_categories=first.age_categories,
    )
    entry = types.SimpleNamespace(
        data=USER_INPUT | {CONF_BIRTH_DATE: "2025-11-15"}, options={}
    )
    coordinator = types.SimpleNamespace(
        data=types.SimpleNamespace(events=(first, second))
    )
    calendar = LibraryCalendar.__new__(LibraryCalendar)
    calendar._entry = entry
    calendar.coordinator = coordinator

    rendered = calendar._calendar_events()

    assert [item.uid for item in rendered] == [
        event_identity(first),
        event_identity(second),
    ]
    assert rendered[0].uid != rendered[1].uid


async def test_webcal_urls_disclose_internal_only_scope(hass: HomeAssistant) -> None:
    hass.config.external_url = None
    hass.config.internal_url = "http://ha.internal.test:8123"

    urls = webcal_subscription_urls(hass, "synthetic-internal-url-token")

    assert urls.http_url.startswith("http://ha.internal.test:8123/api/")
    assert urls.webcal_url.startswith("webcal://ha.internal.test:8123/api/")
    assert urls.external_url_configured is False


def test_webcal_serializes_current_filtered_events_as_rfc5545() -> None:
    event = Event(
        title="Stories, Songs; and Café Fun",
        event_date=date(2026, 7, 22),
        start_time=time(10, 30),
        description=("Stories, songs, and café activities. " * 8).strip(),
        link="https://example.test/events/storytime-1001",
        image_url="",
        branch=BRANCHES["IND"],
        age_categories=("Baby",),
    )
    items = build_calendar_items(
        (event,),
        USER_INPUT | {CONF_BIRTH_DATE: "2025-11-15"},
    )

    rendered = render_icalendar(
        items,
        fetched_at=datetime(2026, 7, 19, 16, 15, tzinfo=ZoneInfo("UTC")),
        refresh_seconds=21600,
        calendar_name="Neighborhood Library Events",
    )
    unfolded = rendered.replace("\r\n ", "")

    assert rendered.startswith("BEGIN:VCALENDAR\r\n")
    assert rendered.endswith("END:VCALENDAR\r\n")
    assert "\n" not in rendered.replace("\r\n", "")
    assert all(len(line.encode("utf-8")) <= 75 for line in rendered.split("\r\n"))
    assert "METHOD:PUBLISH\r\n" in rendered
    assert "X-WR-CALNAME:Neighborhood Library Events\r\n" in rendered
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT6H\r\n" in rendered
    assert "X-PUBLISHED-TTL:PT6H\r\n" in rendered
    assert "DTSTAMP:20260719T161500Z\r\n" in rendered
    assert "DTSTART:20260722T143000Z\r\n" in rendered
    assert "DTEND:20260722T153000Z\r\n" in rendered
    assert "SUMMARY:Stories\\, Songs\\; and Café Fun\r\n" in unfolded
    assert "URL:https://example.test/events/storytime-1001\r\n" in unfolded
    assert "Official details: https://example.test/events/storytime-1001" in unfolded
    assert USER_INPUT[CONF_CHILD_NAME] not in rendered


async def test_webcal_view_is_token_gated_dynamic_and_unloads(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
) -> None:
    token = "valid-synthetic-subscription-token"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Free Library Events",
        unique_id=DOMAIN,
        data=USER_INPUT,
        options={
            CONF_PUBLISH_WEBCAL: True,
            CONF_WEBCAL_TOKEN: token,
            CONF_WEBCAL_NAME: "Neighborhood Library Events",
        },
    )
    entry.add_to_hass(hass)

    async def fetch_filtered(branch, age_category, _coverage_end=None):
        event = Event(
            title=f"{branch.name} Storytime",
            event_date=date(2026, 7, 22),
            start_time=time(10, 30),
            description="Stories and songs for babies with caregivers.",
            link=f"https://example.test/events/{branch.code.lower()}-1001",
            image_url="",
            branch=branch,
            age_categories=(age_category,) if age_category else (),
        )
        return BranchFeed(
            events=(event,),
            age_category=age_category,
            source_count=1,
            parsed_count=1,
            last_event_date=event.event_date,
            ordered=True,
        )

    with patch(
        "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
        side_effect=fetch_filtered,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    client = await hass_client_no_auth()
    response = await client.get(WEBCAL_PATH.format(token="wrong-token"))
    assert response.status == 404
    response = await client.head(WEBCAL_PATH.format(token="wrong-token"))
    assert response.status == 404
    response = await client.get(WEBCAL_PATH.format(token="invalid-☃"))
    assert response.status == 404

    response = await client.get(WEBCAL_PATH.format(token=token))
    assert response.status == 200
    assert response.headers["Content-Type"] == "text/calendar; charset=utf-8"
    assert response.headers["Content-Disposition"] == (
        'inline; filename="free-library-events.ics"'
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["ETag"].startswith('"')
    assert response.headers["ETag"].endswith('"')
    first_body = await response.text()
    first_etag = response.headers["ETag"]
    first_last_modified = response.headers["Last-Modified"]
    first_length = response.headers["Content-Length"]
    assert "Storytime" in first_body
    assert "X-WR-CALNAME:Neighborhood Library Events" in first_body
    assert USER_INPUT[CONF_CHILD_NAME] not in first_body

    response = await client.head(WEBCAL_PATH.format(token=token))
    assert response.status == 200
    assert response.headers["Content-Type"] == "text/calendar; charset=utf-8"
    assert response.headers["Content-Disposition"] == (
        'inline; filename="free-library-events.ics"'
    )
    assert response.headers["ETag"] == first_etag
    assert response.headers["Content-Length"] == first_length
    assert await response.read() == b""

    response = await client.head(
        WEBCAL_PATH.format(token=token), headers={"If-None-Match": first_etag}
    )
    assert response.status == 304
    assert response.headers["ETag"] == first_etag
    assert await response.read() == b""

    response = await client.get(
        WEBCAL_PATH.format(token=token), headers={"If-None-Match": first_etag}
    )
    assert response.status == 304
    assert response.headers["ETag"] == first_etag
    assert await response.read() == b""

    response = await client.get(
        WEBCAL_PATH.format(token=token), headers={"If-None-Match": "*"}
    )
    assert response.status == 304
    assert await response.read() == b""

    response = await client.get(
        WEBCAL_PATH.format(token=token),
        headers={"If-Modified-Since": first_last_modified},
    )
    assert response.status == 304
    assert response.headers["Last-Modified"] == first_last_modified
    assert await response.read() == b""

    response = await client.get(
        WEBCAL_PATH.format(token=token),
        headers={
            "If-None-Match": '"different-representation"',
            "If-Modified-Since": first_last_modified,
        },
    )
    assert response.status == 200
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert token not in repr(diagnostics)
    assert CONF_WEBCAL_TOKEN not in repr(diagnostics)

    added_event = Event(
        title="Newly fetched event",
        event_date=date(2026, 7, 23),
        start_time=time(14, 0),
        description="A newly cached library event.",
        link="https://example.test/events/newly-fetched",
        image_url="",
        branch=BRANCHES["IND"],
        age_categories=("Baby",),
    )
    coordinator = entry.runtime_data
    assert coordinator.data is not None
    coordinator.data = replace(
        coordinator.data,
        events=(*coordinator.data.events, added_event),
        fetched_at=datetime(2026, 7, 19, 17, 0, tzinfo=ZoneInfo("UTC")),
    )

    response = await client.get(WEBCAL_PATH.format(token=token))
    assert response.status == 200
    assert response.headers["ETag"] != first_etag
    assert response.headers["Last-Modified"] == "Sun, 19 Jul 2026 17:00:00 GMT"
    assert "Newly fetched event" in await response.text()

    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_PUBLISH_WEBCAL: False,
            CONF_WEBCAL_TOKEN: token,
        },
    )
    response = await client.get(WEBCAL_PATH.format(token=token))
    assert response.status == 404
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_PUBLISH_WEBCAL: True,
            CONF_WEBCAL_TOKEN: token,
        },
    )
    response = await client.get(WEBCAL_PATH.format(token=token))
    assert response.status == 200

    assert await hass.config_entries.async_unload(entry.entry_id)
    response = await client.get(WEBCAL_PATH.format(token=token))
    assert response.status == 404


def test_feed_coverage_requires_evidence_past_a_capped_date() -> None:
    complete_short_feed = BranchFeed(
        events=(),
        age_category="Baby",
        source_count=9,
        parsed_count=9,
        last_event_date=date(2026, 7, 20),
        ordered=True,
    )
    ambiguous_capped_feed = BranchFeed(
        events=(),
        age_category="Toddler",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 26),
        ordered=True,
    )
    proven_capped_feed = BranchFeed(
        events=(),
        age_category="Toddler",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 27),
        ordered=True,
    )

    assert complete_short_feed.covers_through(date(2026, 7, 26))
    assert not ambiguous_capped_feed.covers_through(date(2026, 7, 26))
    assert proven_capped_feed.covers_through(date(2026, 7, 26))


def test_feed_above_observed_limit_is_still_eligible_for_expansion() -> None:
    feed = BranchFeed(
        events=(),
        age_category="Toddler",
        source_count=11,
        parsed_count=11,
        last_event_date=date(2026, 7, 24),
        ordered=True,
    )

    assert type_expansion_source_keys(
        {"CEN:Toddler": feed},
        date(2023, 11, 7),
        date(2026, 7, 18),
        date(2026, 7, 26),
    ) == ("CEN:Toddler",)


async def test_client_expands_only_an_unresolved_capped_feed() -> None:
    branch = BRANCHES["CEN"]
    base_events = tuple(
        Event(
            title=f"Event {index}",
            event_date=date(2026, 7, 20 + index // 2),
            start_time=time(10, index),
            description="Published event",
            link=f"https://example.test/events/{index}",
            image_url="",
            branch=branch,
            age_categories=("Young Adult",),
        )
        for index in range(10)
    )
    recovered_event = Event(
        title="Recovered event",
        event_date=date(2026, 7, 25),
        start_time=time(12, 0),
        description="Published after the base-feed cap",
        link="https://example.test/events/recovered",
        image_url="",
        branch=branch,
        age_categories=("Young Adult",),
    )
    base_feed = BranchFeed(
        events=base_events,
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 24),
        ordered=True,
    )

    async def fetch_single(_branch, age_category, event_type=None):
        if event_type is None:
            return base_feed
        index = OFFICIAL_EVENT_TYPES.index(event_type)
        events = (base_events[index % len(base_events)],)
        if index == 0:
            events += (recovered_event,)
        return BranchFeed(
            events=events,
            age_category=age_category,
            source_count=len(events),
            parsed_count=len(events),
            last_event_date=max(event.event_date for event in events),
            ordered=True,
        )

    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_fetch_single = AsyncMock(side_effect=fetch_single)

    expanded = await client.async_expand_feed(
        branch, "Young Adult", base_feed, date(2026, 7, 26)
    )

    assert len(expanded.events) == 11
    assert expanded.source_count == 10
    assert expanded.type_shards_queried == len(OFFICIAL_EVENT_TYPES)
    assert expanded.type_shard_failures == ()
    assert expanded.type_shard_blockers == ()
    assert expanded.base_prefix_recovered is True
    assert expanded.expanded_through == date(2026, 7, 26)
    assert expanded.covers_through(date(2026, 7, 26))
    assert client._async_fetch_single.await_count == len(OFFICIAL_EVENT_TYPES)


async def test_client_keeps_recovered_rows_but_discloses_safe_shard_failures() -> None:
    branch = BRANCHES["CEN"]
    event = Event(
        title="Base event",
        event_date=date(2026, 7, 24),
        start_time=time(10, 0),
        description="Published event",
        link="https://example.test/events/base",
        image_url="",
        branch=branch,
        age_categories=("Young Adult",),
    )
    base_feed = BranchFeed(
        events=(event,),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=event.event_date,
        ordered=True,
    )

    async def fetch_single(_branch, age_category, event_type=None):
        if event_type is None:
            return base_feed
        if event_type == OFFICIAL_EVENT_TYPES[0]:
            raise LibraryApiError(SOURCE_ERROR_REQUEST_FAILED)
        if event_type == OFFICIAL_EVENT_TYPES[1]:
            return object()
        return BranchFeed(
            events=(event,),
            age_category=age_category,
            source_count=1,
            parsed_count=1,
            last_event_date=event.event_date,
            ordered=True,
        )

    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_fetch_single = AsyncMock(side_effect=fetch_single)

    expanded = await client.async_expand_feed(
        branch, "Young Adult", base_feed, date(2026, 7, 26)
    )

    assert expanded.events == (event,)
    assert expanded.type_shard_failures == (
        f"{OFFICIAL_EVENT_TYPES[0]}: {SOURCE_ERROR_REQUEST_FAILED}",
        f"{OFFICIAL_EVENT_TYPES[1]}: {SOURCE_ERROR_UNEXPECTED}",
    )
    assert expanded.expanded_through is None
    assert not expanded.covers_through(date(2026, 7, 26))


async def test_client_records_a_successful_capped_type_shard_blocker() -> None:
    branch = BRANCHES["CEN"]
    base_event = Event(
        title="Base event",
        event_date=date(2026, 7, 24),
        start_time=time(10, 0),
        description="Published event",
        link="https://example.test/events/base",
        image_url="",
        branch=branch,
        age_categories=("Young Adult",),
    )
    base_feed = BranchFeed(
        events=(base_event,),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=base_event.event_date,
        ordered=True,
    )

    async def fetch_single(_branch, age_category, event_type=None):
        if event_type == "Community Events":
            return BranchFeed(
                events=(base_event,),
                age_category=age_category,
                source_count=10,
                parsed_count=10,
                last_event_date=date(2026, 7, 25),
                ordered=True,
            )
        return BranchFeed(
            events=(base_event,),
            age_category=age_category,
            source_count=1,
            parsed_count=1,
            last_event_date=base_event.event_date,
            ordered=True,
        )

    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_fetch_single = AsyncMock(side_effect=fetch_single)

    expanded = await client.async_expand_feed(
        branch, "Young Adult", base_feed, date(2026, 7, 26)
    )

    assert expanded.type_shard_failures == ()
    assert expanded.type_shard_blockers == (
        TypeShardBlocker(
            event_type="Community Events",
            reason=TYPE_SHARD_BLOCKER_CAPPED,
            source_count=10,
            parsed_count=10,
            last_event_date=date(2026, 7, 25),
        ),
    )
    assert expanded.base_prefix_recovered is True
    assert expanded.expanded_through is None

    data = types.SimpleNamespace(
        source_statuses={"CEN:Young Adult": expanded}, source_errors={}
    )
    failures, limitations = supplemental_coverage(
        data,
        date(2025, 11, 7),
        date(2026, 7, 20),
        date(2026, 7, 26),
    )
    assert failures == []
    assert len(limitations) == 1
    assert "Community Events returned 10 items through July 25" in limitations[0]
    assert "proving coverage through July 26" in limitations[0]


@pytest.mark.parametrize(
    ("reason", "source_count", "parsed_count", "last_event_date", "ordered"),
    (
        (TYPE_SHARD_BLOCKER_PARSE_INCOMPLETE, 10, 9, date(2026, 7, 27), True),
        (TYPE_SHARD_BLOCKER_UNORDERED, 10, 10, date(2026, 7, 27), False),
        (TYPE_SHARD_BLOCKER_MISSING_BOUNDARY, 10, 10, None, True),
    ),
)
async def test_supplemental_type_shard_integrity_blockers_are_partial(
    reason: str,
    source_count: int,
    parsed_count: int,
    last_event_date: date | None,
    ordered: bool,
) -> None:
    branch = BRANCHES["CEN"]
    event = Event(
        title="Base event",
        event_date=date(2026, 7, 24),
        start_time=time(10, 0),
        description="Published event",
        link="https://example.test/events/base",
        image_url="",
        branch=branch,
        age_categories=("Young Adult",),
    )
    base_feed = BranchFeed(
        events=(event,),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=event.event_date,
        ordered=True,
    )

    async def fetch_single(_branch, age_category, event_type=None):
        if event_type == "Community Events":
            return BranchFeed(
                events=(event,),
                age_category=age_category,
                source_count=source_count,
                parsed_count=parsed_count,
                last_event_date=last_event_date,
                ordered=ordered,
            )
        return BranchFeed(
            events=(event,),
            age_category=age_category,
            source_count=1,
            parsed_count=1,
            last_event_date=event.event_date,
            ordered=True,
        )

    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_fetch_single = AsyncMock(side_effect=fetch_single)
    feed = await client.async_expand_feed(
        branch, "Young Adult", base_feed, date(2026, 7, 26)
    )

    assert feed.type_shard_blockers == (
        TypeShardBlocker(
            event_type="Community Events",
            reason=reason,
            source_count=source_count,
            parsed_count=parsed_count,
            last_event_date=last_event_date,
        ),
    )
    assert feed.base_prefix_recovered is True
    assert feed.expanded_through is None
    data = types.SimpleNamespace(
        source_statuses={"CEN:Young Adult": feed}, source_errors={}
    )

    failures, limitations = supplemental_coverage(
        data,
        date(2025, 11, 7),
        date(2026, 7, 20),
        date(2026, 7, 26),
    )

    assert len(failures) == 1
    assert "Community Events" in failures[0]
    assert limitations == []


def test_missing_base_prefix_recovery_remains_a_healthy_limitation() -> None:
    feed = BranchFeed(
        events=(),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 24),
        ordered=True,
        type_shards_queried=len(OFFICIAL_EVENT_TYPES),
        base_prefix_recovered=False,
    )
    data = types.SimpleNamespace(
        source_statuses={"CEN:Young Adult": feed}, source_errors={}
    )

    failures, limitations = supplemental_coverage(
        data,
        date(2025, 11, 7),
        date(2026, 7, 20),
        date(2026, 7, 26),
    )

    assert failures == []
    assert len(limitations) == 1
    assert "did not recover every base-feed item" in limitations[0]


def test_state_expansion_details_bound_failure_examples() -> None:
    failures = tuple(f"Type {index}: offline" for index in range(19))
    blockers = tuple(
        TypeShardBlocker(
            event_type=f"Type {index}",
            reason=TYPE_SHARD_BLOCKER_CAPPED,
            source_count=10,
            parsed_count=10,
            last_event_date=date(2026, 7, 24),
        )
        for index in range(19)
    )
    feed = BranchFeed(
        events=(),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 24),
        ordered=True,
        type_shards_queried=19,
        type_shard_failures=failures,
        type_shard_blockers=blockers,
        base_prefix_recovered=False,
    )
    data = types.SimpleNamespace(source_statuses={"CEN:Young Adult": feed})

    details = next(iter(source_expansion_details(data).values()))

    assert details["type_feed_failure_count"] == 19
    assert details["type_feed_failure_examples"] == list(failures[:3])
    assert "type_feed_failures" not in details
    assert details["type_feed_blocker_count"] == 19
    assert details["type_feed_blocker_examples"] == [
        {
            "event_type": f"Type {index}",
            "reason": TYPE_SHARD_BLOCKER_CAPPED,
            "published_item_count": 10,
            "parsed_item_count": 10,
            "last_event_date": "2026-07-24",
        }
        for index in range(3)
    ]
    assert details["base_prefix_recovered"] is False


async def test_diagnostics_include_all_structured_type_feed_blockers(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    blockers = tuple(
        TypeShardBlocker(
            event_type=f"Type {index}",
            reason=TYPE_SHARD_BLOCKER_CAPPED,
            source_count=10,
            parsed_count=10,
            last_event_date=date(2026, 7, 24),
        )
        for index in range(4)
    )
    feed = BranchFeed(
        events=(),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 24),
        ordered=True,
        type_shards_queried=len(OFFICIAL_EVENT_TYPES),
        type_shard_blockers=blockers,
        base_prefix_recovered=True,
    )
    entry.runtime_data = types.SimpleNamespace(
        data=LibraryData(
            events=(),
            source_counts={"CEN": 0},
            source_statuses={"CEN:Young Adult": feed},
            source_errors={},
            fetched_at=datetime(2026, 7, 18, tzinfo=UTC),
        ),
        last_update_success=True,
        last_exception=None,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    source = next(iter(diagnostics["sources"].values()))
    assert len(source["type_feed_blockers"]) == 4
    assert source["type_feed_blockers"][0] == {
        "event_type": "Type 0",
        "reason": TYPE_SHARD_BLOCKER_CAPPED,
        "published_item_count": 10,
        "parsed_item_count": 10,
        "last_event_date": "2026-07-24",
    }
    assert source["base_prefix_recovered"] is True


async def test_client_bounds_all_rss_request_concurrency() -> None:
    branch = BRANCHES["CEN"]
    base_feed = BranchFeed(
        events=(),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 24),
        ordered=True,
    )
    active = 0
    peak = 0

    async def fetch_payload(_url):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return b"<?xml version='1.0'?><rss><channel></channel></rss>"

    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_get = AsyncMock(side_effect=fetch_payload)

    await asyncio.gather(
        *(
            client.async_expand_feed(
                branch, "Young Adult", base_feed, date(2026, 7, 26)
            )
            for _ in range(3)
        )
    )

    assert peak == MAX_RSS_REQUEST_CONCURRENCY
    assert active == 0


async def test_client_base_fetch_does_not_expand() -> None:
    feed = BranchFeed(
        events=(),
        age_category="Baby",
        source_count=9,
        parsed_count=9,
        last_event_date=date(2026, 7, 20),
        ordered=True,
    )
    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_fetch_single = AsyncMock(return_value=feed)

    result = await client.async_fetch_feed(BRANCHES["CEN"], "Baby")

    assert result is feed
    client._async_fetch_single.assert_awaited_once()


async def test_client_does_not_chain_private_transport_details() -> None:
    private_detail = "synthetic private transport detail"
    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_get = AsyncMock(side_effect=TimeoutError(private_detail))

    with pytest.raises(LibraryApiError, match=SOURCE_ERROR_REQUEST_FAILED) as failure:
        await client.async_fetch_feed(BRANCHES["CEN"], "Baby")

    assert failure.value.__cause__ is None
    assert failure.value.retryable is True
    assert private_detail not in repr(failure.value)


@pytest.mark.parametrize(
    ("status", "retryable"),
    ((404, False), (408, True), (429, True), (500, True), (503, True)),
)
async def test_client_classifies_retryable_http_failures(
    status: int, retryable: bool
) -> None:
    error = aiohttp.ClientResponseError(
        request_info=Mock(),
        history=(),
        status=status,
    )
    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_get = AsyncMock(side_effect=error)

    with pytest.raises(LibraryApiError) as failure:
        await client.async_fetch_feed(BRANCHES["CEN"], "Baby")

    assert failure.value.category == SOURCE_ERROR_REQUEST_FAILED
    assert failure.value.retryable is retryable


async def test_client_rejects_an_oversized_rss_response() -> None:
    response = types.SimpleNamespace(
        status=200,
        headers={},
        content=types.SimpleNamespace(
            readexactly=AsyncMock(return_value=b"x" * (MAX_RSS_RESPONSE_BYTES + 1))
        ),
        raise_for_status=lambda: None,
    )

    class ResponseContext:
        async def __aenter__(self):
            return response

        async def __aexit__(self, *_args):
            return None

    session = types.SimpleNamespace(get=lambda *_args, **_kwargs: ResponseContext())
    client = LibraryClient(session)

    with pytest.raises(LibraryApiError, match=SOURCE_ERROR_RESPONSE_TOO_LARGE):
        await client._async_get(
            "https://libwww.freelibrary.org/rss/eventsrss.cfm?location=CEN"
        )


async def test_client_returns_a_complete_response_below_the_size_limit() -> None:
    payload = b"<?xml version='1.0'?><rss><channel></channel></rss>"

    async def readexactly(_size):
        raise asyncio.IncompleteReadError(payload, MAX_RSS_RESPONSE_BYTES + 1)

    response = types.SimpleNamespace(
        status=200,
        headers={},
        content=types.SimpleNamespace(readexactly=readexactly),
        raise_for_status=lambda: None,
    )

    class ResponseContext:
        async def __aenter__(self):
            return response

        async def __aexit__(self, *_args):
            return None

    session = types.SimpleNamespace(get=lambda *_args, **_kwargs: ResponseContext())
    client = LibraryClient(session)

    assert (
        await client._async_get(
            "https://libwww.freelibrary.org/rss/eventsrss.cfm?location=CEN"
        )
        == payload
    )


async def test_client_follows_only_trusted_https_rss_redirects() -> None:
    payload = b"<?xml version='1.0'?><rss><channel></channel></rss>"

    async def complete_read(_size):
        raise asyncio.IncompleteReadError(payload, MAX_RSS_RESPONSE_BYTES + 1)

    redirect_response = types.SimpleNamespace(
        status=302,
        headers={"Location": "/rss/redirected.cfm"},
    )
    final_response = types.SimpleNamespace(
        status=200,
        headers={},
        content=types.SimpleNamespace(readexactly=complete_read),
        raise_for_status=lambda: None,
    )
    responses = iter((redirect_response, final_response))
    requests = []

    class ResponseContext:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, *_args):
            return None

    def get(url, **kwargs):
        requests.append((url, kwargs))
        return ResponseContext(next(responses))

    client = LibraryClient(types.SimpleNamespace(get=get))

    assert (
        await client._async_get(
            "https://libwww.freelibrary.org/rss/eventsrss.cfm?location=CEN"
        )
        == payload
    )
    assert [request[0] for request in requests] == [
        "https://libwww.freelibrary.org/rss/eventsrss.cfm?location=CEN",
        "https://libwww.freelibrary.org/rss/redirected.cfm",
    ]
    assert all(request[1]["allow_redirects"] is False for request in requests)


@pytest.mark.parametrize(
    "location",
    (
        "https://example.test/feed",
        "https://[::1]/feed",
        "http://libwww.freelibrary.org/feed",
        "https://libwww.freelibrary.org:8443/feed",
        "https://libwww.freelibrary.org:not-a-port/feed",
    ),
)
async def test_client_rejects_untrusted_rss_redirects(location: str) -> None:
    response = types.SimpleNamespace(
        status=302,
        headers={"Location": location},
        content=types.SimpleNamespace(
            readexactly=AsyncMock(
                side_effect=asyncio.IncompleteReadError(b"", MAX_RSS_RESPONSE_BYTES + 1)
            )
        ),
        raise_for_status=lambda: None,
    )

    class ResponseContext:
        async def __aenter__(self):
            return response

        async def __aexit__(self, *_args):
            return None

    session = types.SimpleNamespace(get=lambda *_args, **_kwargs: ResponseContext())
    client = LibraryClient(session)

    with pytest.raises(LibraryApiError, match=SOURCE_ERROR_UNSAFE_REDIRECT):
        await client._async_get(
            "https://libwww.freelibrary.org/rss/eventsrss.cfm?location=CEN"
        )


async def test_coordinator_expands_every_current_age_source_before_supplemental_sources(
    hass: HomeAssistant,
) -> None:
    async def fetch_feed(_branch, age_category):
        return BranchFeed(
            events=(),
            age_category=age_category,
            source_count=10,
            parsed_count=10,
            last_event_date=date(2026, 7, 24),
            ordered=True,
        )

    async def expand_feed(branch, age_category, feed, coverage_end):
        event = Event(
            title=f"Recovered {age_category} event",
            event_date=date(2026, 7, 25),
            start_time=time(10, 0),
            description="Recovered through official type expansion",
            link=f"https://example.test/events/{branch.code}/{age_category}",
            image_url="",
            branch=branch,
            age_categories=(age_category,),
        )
        return BranchFeed(
            events=(event,),
            age_category=feed.age_category,
            source_count=feed.source_count,
            parsed_count=feed.parsed_count,
            last_event_date=feed.last_event_date,
            ordered=True,
            type_shards_queried=len(OFFICIAL_EVENT_TYPES),
            expanded_through=coverage_end,
        )

    client = types.SimpleNamespace(
        async_fetch_feed=AsyncMock(side_effect=fetch_feed),
        async_expand_feed=AsyncMock(side_effect=expand_feed),
    )
    coordinator = LibraryDataCoordinator(
        hass,
        _entry(),
        client,
        tuple(BRANCHES.values()),
        date(2023, 11, 7),
        timedelta(hours=6),
    )

    with patch(
        "custom_components.free_library_events.coordinator.dt_util.now",
        return_value=datetime(2026, 7, 18, tzinfo=LOCAL_TIME_ZONE),
    ):
        data = await coordinator._async_update_data()

    expanded_sources = [
        (call.args[0].code, call.args[1])
        for call in client.async_expand_feed.await_args_list
    ]
    expected_current_sources = {
        (branch.code, category)
        for branch in BRANCHES.values()
        for category in ("Baby", "Toddler", "Preschool")
    }
    assert len(expanded_sources) == MAX_TYPE_EXPANSIONS_PER_REFRESH
    assert set(expanded_sources) == expected_current_sources
    assert len(data.events) == MAX_TYPE_EXPANSIONS_PER_REFRESH


async def test_coordinator_bounds_a_stalled_type_expansion(
    hass: HomeAssistant,
) -> None:
    async def fetch_feed(_branch, age_category):
        return BranchFeed(
            events=(),
            age_category=age_category,
            source_count=10,
            parsed_count=10,
            last_event_date=date(2026, 7, 24),
            ordered=True,
        )

    async def expand_feed(*_args):
        await asyncio.sleep(60)

    client = types.SimpleNamespace(
        async_fetch_feed=AsyncMock(side_effect=fetch_feed),
        async_expand_feed=AsyncMock(side_effect=expand_feed),
    )
    coordinator = LibraryDataCoordinator(
        hass,
        _entry(),
        client,
        (BRANCHES["CEN"],),
        date(1990, 1, 1),
        timedelta(hours=6),
    )

    with (
        patch(
            "custom_components.free_library_events.coordinator.dt_util.now",
            return_value=datetime(2026, 7, 18, tzinfo=LOCAL_TIME_ZONE),
        ),
        patch(
            "custom_components.free_library_events.coordinator."
            "TYPE_EXPANSION_TIMEOUT_SECONDS",
            0.001,
        ),
    ):
        data = await coordinator._async_update_data()

    status = data.source_statuses["CEN:Adult"]
    assert status.events == ()
    assert status.type_shards_queried == len(OFFICIAL_EVENT_TYPES)
    assert status.type_shard_failures == (SOURCE_ERROR_EXPANSION_TIMEOUT,)


async def test_client_propagates_type_shard_cancellation() -> None:
    branch = BRANCHES["CEN"]
    base_feed = BranchFeed(
        events=(),
        age_category="Young Adult",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 24),
        ordered=True,
    )

    async def fetch_single(_branch, age_category, event_type=None):
        if event_type == OFFICIAL_EVENT_TYPES[0]:
            raise asyncio.CancelledError
        return BranchFeed(
            events=(),
            age_category=age_category,
            source_count=0,
            parsed_count=0,
            last_event_date=None,
            ordered=True,
        )

    client = LibraryClient(None)  # type: ignore[arg-type]
    client._async_fetch_single = AsyncMock(side_effect=fetch_single)

    with pytest.raises(asyncio.CancelledError):
        await client.async_expand_feed(
            branch, "Young Adult", base_feed, date(2026, 7, 26)
        )


def test_source_plan_is_recomputed_for_the_target_age_window() -> None:
    keys = ("CEN:Baby", "CEN:Toddler", "CEN:Preschool", "CEN:School Age")

    assert source_keys_for_window(
        keys,
        date(2025, 1, 15),
        date(2026, 7, 20),
        date(2026, 7, 26),
    ) == ["CEN:Baby", "CEN:Toddler"]


def test_supplemental_coverage_separates_failures_from_feed_limits() -> None:
    limited = BranchFeed(
        events=(),
        age_category="School Age",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 25),
        ordered=True,
    )
    malformed = BranchFeed(
        events=(),
        age_category="Preschool",
        source_count=4,
        parsed_count=3,
        last_event_date=date(2026, 7, 27),
        ordered=True,
    )
    data = types.SimpleNamespace(
        source_statuses={"SWK:School Age": limited, "CEN:Preschool": malformed},
        source_errors={"PCI:Young Adult": SOURCE_ERROR_REQUEST_FAILED},
    )

    failures, limitations = supplemental_coverage(
        data,
        date(2025, 11, 7),
        date(2026, 7, 20),
        date(2026, 7, 26),
    )

    assert len(failures) == 2
    assert any(
        "Parkway Central Library" in item and "only 3" in item for item in failures
    )
    assert any(
        "Philadelphia City Institute" in item
        and "library source request failed" in item
        for item in failures
    )
    assert len(limitations) == 1
    assert "Charles Santore Library" in limitations[0]
    assert "later broadly inclusive events may be missing" in limitations[0]


async def test_coordinator_recomputes_age_feeds_as_time_advances(
    hass: HomeAssistant,
) -> None:
    """The same config entry advances to new official feeds without hard-coding."""

    entry = _entry()

    async def fetch_feed(_branch, age_category, _coverage_end=None):
        return BranchFeed(
            events=(),
            age_category=age_category,
            source_count=0,
            parsed_count=0,
            last_event_date=None,
            ordered=True,
        )

    client = types.SimpleNamespace(async_fetch_feed=AsyncMock(side_effect=fetch_feed))
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        (BRANCHES["CEN"],),
        date(2008, 8, 15),
        timedelta(hours=6),
    )

    with patch(
        "custom_components.free_library_events.coordinator.dt_util.now",
        return_value=datetime(2026, 4, 1, tzinfo=LOCAL_TIME_ZONE),
    ):
        await coordinator._async_update_data()
    assert [call.args[1] for call in client.async_fetch_feed.await_args_list] == [
        "Baby",
        "Toddler",
        "Preschool",
        "School Age",
        "Young Adult",
    ]

    client.async_fetch_feed.reset_mock()
    with patch(
        "custom_components.free_library_events.coordinator.dt_util.now",
        return_value=datetime(2026, 10, 1, tzinfo=LOCAL_TIME_ZONE),
    ):
        await coordinator._async_update_data()
    assert [call.args[1] for call in client.async_fetch_feed.await_args_list] == [
        "Young Adult",
        "Adult",
    ]


async def test_status_separates_a_healthy_supplemental_limit_from_partial_failure(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    async def fetch_feed(_branch, age_category, _coverage_end=None):
        is_limited = age_category == "Young Adult"
        return BranchFeed(
            events=(),
            age_category=age_category,
            source_count=10 if is_limited else 1,
            parsed_count=10 if is_limited else 1,
            last_event_date=date(2026, 7, 25 if is_limited else 27),
            ordered=True,
            type_shards_queried=len(OFFICIAL_EVENT_TYPES) if is_limited else 0,
        )

    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            side_effect=fetch_feed,
        ),
        patch(
            "custom_components.free_library_events.sensor.dt_util.now",
            return_value=datetime(2026, 7, 18, tzinfo=LOCAL_TIME_ZONE),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    status = hass.states.get("sensor.free_library_events_status")
    assert status is not None
    assert status.state == "limited"
    assert status.attributes["current_age_coverage_complete"] is True
    assert status.attributes["supplemental_age_coverage_complete"] is False
    assert status.attributes["supplemental_age_failures"] == []
    assert len(status.attributes["supplemental_age_limitations"]) == 4
    assert len(status.attributes["expanded_capped_sources"]) == 4

    with patch(
        "custom_components.free_library_events.dt_util.now",
        return_value=datetime(2026, 7, 18, tzinfo=LOCAL_TIME_ZONE),
    ):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            {ATTR_FORCE_REFRESH: False},
            blocking=True,
            return_response=True,
        )
    assert response["metadata"]["supplemental_age_failures"] == []
    assert len(response["metadata"]["supplemental_age_limitations"]) == 4
    assert len(response["metadata"]["expanded_capped_sources"]) == 4
    assert "later broadly inclusive events may be missing" not in response["message"]


async def test_digest_discloses_an_operational_supplemental_failure(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    async def fetch_feed(branch, age_category, _coverage_end=None):
        if branch.code == "SWK" and age_category == "Young Adult":
            raise LibraryApiError(SOURCE_ERROR_REQUEST_FAILED)
        event = Event(
            title="Baby Storytime",
            event_date=date(2026, 7, 22),
            start_time=time(10, 30),
            description="Stories and songs for babies with caregivers.",
            link=f"https://example.test/events/{branch.code.lower()}-1001",
            image_url="",
            branch=branch,
            age_categories=(age_category,),
        )
        return BranchFeed(
            events=(event,),
            age_category=age_category,
            source_count=1,
            parsed_count=1,
            last_event_date=event.event_date,
            ordered=True,
        )

    with (
        patch(
            "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
            side_effect=fetch_feed,
        ),
        patch(
            "custom_components.free_library_events.dt_util.now",
            return_value=datetime(2026, 7, 17, tzinfo=LOCAL_TIME_ZONE),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            {ATTR_FORCE_REFRESH: False},
            blocking=True,
            return_response=True,
        )

    assert "Some library listings may be missing" in response["message"]
    assert "Charles Santore Library — Young Adult" not in response["message"]
    assert "offline" not in response["message"]
    assert response["metadata"]["supplemental_age_failures"] == [
        (
            "Charles Santore Library — Young Adult could not be loaded: "
            "library source request failed"
        )
    ]


async def test_coordinator_retains_partial_source_success(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    success = BranchFeed(
        events=(),
        age_category="Baby",
        source_count=3,
        parsed_count=0,
        last_event_date=None,
        ordered=True,
    )

    async def fetch_feed(_branch, age_category, _coverage_end=None):
        if age_category == "Baby":
            return success
        raise LibraryApiError(SOURCE_ERROR_REQUEST_FAILED)

    client = types.SimpleNamespace(async_fetch_feed=AsyncMock(side_effect=fetch_feed))
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        (BRANCHES["SWK"],),
        date(2025, 1, 15),
        timedelta(hours=6),
    )
    data = await coordinator._async_update_data()
    assert data.source_counts == {"SWK": 0}
    assert data.source_errors == {
        "SWK:Toddler": SOURCE_ERROR_REQUEST_FAILED,
        "SWK:Preschool": SOURCE_ERROR_REQUEST_FAILED,
        "SWK:School Age": SOURCE_ERROR_REQUEST_FAILED,
        "SWK:Young Adult": SOURCE_ERROR_REQUEST_FAILED,
    }
    assert list(data.source_statuses) == ["SWK:Baby"]
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.requested_source_count == 5
    assert coordinator.last_attempt.successful_source_count == 1
    assert coordinator.last_attempt.failed_source_count == 4
    assert coordinator.last_attempt.retryable_failure_count == 0
    assert coordinator.last_attempt.expedited_retry_scheduled is False
    with pytest.raises(TypeError):
        data.source_counts["SWK"] = 1
    with pytest.raises(TypeError):
        data.source_statuses["SWK:Toddler"] = success
    with pytest.raises(TypeError):
        data.source_errors["SWK:Baby"] = SOURCE_ERROR_REQUEST_FAILED


def test_library_data_detaches_nested_mappings() -> None:
    source_counts = {"SWK": 1}
    source_statuses: dict[str, BranchFeed] = {}
    source_errors = {"SWK:Baby": SOURCE_ERROR_REQUEST_FAILED}
    snapshot = LibraryData(
        events=(),
        source_counts=source_counts,
        source_statuses=source_statuses,
        source_errors=source_errors,
        fetched_at=datetime(2026, 8, 8, tzinfo=ZoneInfo("UTC")),
    )

    source_counts["SWK"] = 2
    source_statuses["SWK:Baby"] = Mock()
    source_errors.clear()

    assert snapshot.source_counts == {"SWK": 1}
    assert snapshot.source_statuses == {}
    assert snapshot.source_errors == {
        "SWK:Baby": SOURCE_ERROR_REQUEST_FAILED,
    }


async def test_coordinator_does_not_retain_unexpected_exception_text(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    private_detail = "synthetic private source detail"
    success = BranchFeed(
        events=(),
        age_category="Baby",
        source_count=0,
        parsed_count=0,
        last_event_date=None,
        ordered=True,
    )

    async def fetch_feed(_branch, age_category, _coverage_end=None):
        if age_category == "Baby":
            return success
        if age_category == "Toddler":
            return object()
        raise RuntimeError(private_detail)

    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        types.SimpleNamespace(async_fetch_feed=AsyncMock(side_effect=fetch_feed)),
        (BRANCHES["SWK"],),
        date(2025, 1, 15),
        timedelta(hours=6),
    )

    data = await coordinator._async_update_data()

    assert set(data.source_errors.values()) == {SOURCE_ERROR_UNEXPECTED}
    assert private_detail not in repr(data)


async def test_diagnostics_categorize_unexpected_coordinator_exception(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    private_detail = "synthetic private coordinator detail"
    entry.runtime_data = types.SimpleNamespace(
        data=None,
        last_update_success=False,
        last_exception=RuntimeError(private_detail),
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["coordinator"]["last_error_category"] == "unexpected"
    assert private_detail not in repr(diagnostics)


async def test_coordinator_retains_complete_failure_evidence_without_retrying_policy_errors(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    client = types.SimpleNamespace(
        async_fetch_feed=AsyncMock(
            side_effect=LibraryApiError(SOURCE_ERROR_REQUEST_FAILED)
        )
    )
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        (BRANCHES["SWK"],),
        date(2025, 1, 15),
        timedelta(hours=6),
    )
    with pytest.raises(UpdateFailed) as failure:
        await coordinator._async_update_data()

    assert failure.value.translation_domain == DOMAIN
    assert failure.value.translation_key == "library_source_update_failed"
    assert failure.value.retry_after is None
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.requested_source_count == 5
    assert coordinator.last_attempt.successful_source_count == 0
    assert coordinator.last_attempt.failed_source_count == 5
    assert coordinator.last_attempt.retryable_failure_count == 0
    assert coordinator.last_attempt.error_category_counts == {
        SOURCE_ERROR_REQUEST_FAILED: 5
    }
    assert coordinator.last_attempt.expedited_retry_scheduled is False
    with pytest.raises(TypeError):
        coordinator.last_attempt.source_errors["SWK:Baby"] = SOURCE_ERROR_UNEXPECTED


async def test_coordinator_bounds_expedited_retry_and_exposes_current_attempt(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    client = types.SimpleNamespace(
        async_fetch_feed=AsyncMock(
            side_effect=LibraryApiError(
                SOURCE_ERROR_REQUEST_FAILED,
                retryable=True,
            )
        )
    )
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        (BRANCHES["SWK"],),
        date(2025, 1, 15),
        timedelta(hours=6),
    )

    with pytest.raises(UpdateFailed) as first_failure:
        await coordinator._async_update_data()

    assert first_failure.value.retry_after == 5 * 60
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.retryable_failure_count == 5
    assert coordinator.last_attempt.expedited_retry_scheduled is True

    with pytest.raises(UpdateFailed) as second_failure:
        await coordinator._async_update_data()

    assert second_failure.value.retry_after is None
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.expedited_retry_scheduled is False

    success = BranchFeed(
        events=(),
        age_category="Baby",
        source_count=0,
        parsed_count=0,
        last_event_date=None,
        ordered=True,
    )
    client.async_fetch_feed.side_effect = None
    client.async_fetch_feed.return_value = success
    data = await coordinator._async_update_data()
    coordinator.async_set_updated_data(data)
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.successful_source_count == 5

    client.async_fetch_feed.return_value = None
    client.async_fetch_feed.side_effect = LibraryApiError(
        SOURCE_ERROR_REQUEST_FAILED,
        retryable=True,
    )
    with pytest.raises(UpdateFailed) as recovered_streak_failure:
        await coordinator._async_update_data()

    assert recovered_streak_failure.value.retry_after == 5 * 60
    coordinator.async_set_update_error(recovered_streak_failure.value)
    entry.runtime_data = coordinator
    status = LibraryStatusSensor(entry, coordinator)
    status_attributes = status.extra_state_attributes
    assert status.available is True
    assert status.native_value == "error"
    assert status_attributes["cached_events"] == 0
    assert status_attributes["last_attempt_requested_sources"] == 5
    assert status_attributes["last_attempt_successful_sources"] == 0
    assert status_attributes["last_attempt_failed_sources"] == 5
    assert status_attributes["last_attempt_retryable_failures"] == 5
    assert status_attributes["last_attempt_error_categories"] == {
        SOURCE_ERROR_REQUEST_FAILED: 5
    }
    assert status_attributes["expedited_retry_scheduled"] is True
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["cached_event_count"] == 0
    assert all(source["available"] for source in diagnostics["sources"].values())
    assert diagnostics["last_attempt"] == {
        "completed_at": coordinator.last_attempt.completed_at.isoformat(),
        "requested_source_count": 5,
        "successful_source_count": 0,
        "failed_source_count": 5,
        "retryable_failure_count": 5,
        "error_category_counts": {SOURCE_ERROR_REQUEST_FAILED: 5},
        "expedited_retry_scheduled": True,
        "sources": {
            f"Charles Santore Library — {category}": {
                "available": False,
                "error_category": SOURCE_ERROR_REQUEST_FAILED,
            }
            for category in (
                "Baby",
                "Toddler",
                "Preschool",
                "School Age",
                "Young Adult",
            )
        },
    }


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Legacy child-specific title",
        unique_id=DOMAIN,
        data=USER_INPUT,
    )
