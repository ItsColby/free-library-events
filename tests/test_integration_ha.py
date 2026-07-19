"""Home Assistant integration tests for Free Library Events."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
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
    MAX_TYPE_SHARD_CONCURRENCY,
    OFFICIAL_EVENT_TYPES,
    BranchFeed,
    LibraryApiError,
    LibraryClient,
)
from custom_components.free_library_events.config import (  # noqa: E402
    normalize_config,
    selected_branches,
)
from custom_components.free_library_events.const import (  # noqa: E402
    ATTR_FORCE_REFRESH,
    CONF_BIRTH_DATE,
    CONF_CALENDAR_DURATION,
    CONF_CHILD_NAME,
    CONF_FILTER_MODE,
    CONF_INCLUDE_INDEPENDENCE,
    CONF_INCLUDE_PARKWAY_CENTRAL,
    CONF_INCLUDE_PCI,
    CONF_INCLUDE_SANTORE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    SERVICE_RENDER_DIGEST,
)
from custom_components.free_library_events.coordinator import (  # noqa: E402
    MAX_TYPE_EXPANSIONS_PER_REFRESH,
    LibraryDataCoordinator,
    source_keys_for_window,
    supplemental_coverage,
)
from custom_components.free_library_events.diagnostics import (  # noqa: E402
    async_get_config_entry_diagnostics,
)
from custom_components.free_library_events.digest import (  # noqa: E402
    BRANCHES,
    DescriptionLink,
    Event,
)


pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

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


def test_all_sources_default_on_for_legacy_and_new_entries() -> None:
    legacy_input = {
        key: value
        for key, value in USER_INPUT.items()
        if key not in {CONF_INCLUDE_PARKWAY_CENTRAL, CONF_INCLUDE_PCI}
    }
    legacy_config = normalize_config(legacy_input)
    assert legacy_config[CONF_INCLUDE_PARKWAY_CENTRAL] is True
    assert legacy_config[CONF_INCLUDE_PCI] is True
    assert [branch.code for branch in selected_branches(legacy_config)] == [
        "SWK",
        "IND",
        "CEN",
        "PCI",
    ]


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
            image_url="",
            branch=branch,
            age_categories=(age_category,) if age_category else (),
            end_at=datetime(2026, 7, 22, 12, 0),
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

    with patch(
        "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
        side_effect=fetch_filtered,
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
    assert status_state.attributes["next_week_events"] == 4
    assert status_state.attributes["current_age_coverage_complete"] is True
    assert status_state.attributes["supplemental_age_coverage_complete"] is True
    assert status_state.attributes["expanded_capped_sources"] == {}
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
        return_value=datetime(2026, 7, 17),
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
    assert "Avery" in response["subject"]

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "Avery" not in repr(diagnostics)
    assert "2025-01-15" not in repr(diagnostics)
    assert list(diagnostics["sources"]) == [
        f"{branch.name} — {category}"
        for branch in BRANCHES.values()
        for category in ("Baby", "Toddler", "Preschool", "School Age", "Young Adult")
    ]


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
    assert expanded.expanded_through == date(2026, 7, 26)
    assert expanded.covers_through(date(2026, 7, 26))
    assert client._async_fetch_single.await_count == len(OFFICIAL_EVENT_TYPES)


async def test_client_keeps_recovered_rows_but_discloses_a_shard_failure() -> None:
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
            raise LibraryApiError("offline")
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
    assert len(expanded.type_shard_failures) == 1
    assert expanded.expanded_through is None
    assert not expanded.covers_through(date(2026, 7, 26))


async def test_client_bounds_type_shard_concurrency() -> None:
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

    async def fetch_single(_branch, age_category, _event_type=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
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

    await asyncio.gather(
        *(
            client.async_expand_feed(
                branch, "Young Adult", base_feed, date(2026, 7, 26)
            )
            for _ in range(3)
        )
    )

    assert peak == MAX_TYPE_SHARD_CONCURRENCY
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


async def test_coordinator_bounds_and_prioritizes_type_expansion(
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
            link=f"https://example.test/events/{age_category}",
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
        (BRANCHES["CEN"],),
        date(2025, 11, 7),
        timedelta(hours=6),
    )

    with patch(
        "custom_components.free_library_events.coordinator.dt_util.now",
        return_value=datetime(2026, 7, 18),
    ):
        data = await coordinator._async_update_data()

    expanded_categories = [
        call.args[1] for call in client.async_expand_feed.await_args_list
    ]
    assert len(expanded_categories) == MAX_TYPE_EXPANSIONS_PER_REFRESH
    assert expanded_categories[0] == "Baby"
    assert "Young Adult" not in expanded_categories
    assert len(data.events) == MAX_TYPE_EXPANSIONS_PER_REFRESH


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
        source_errors={"PCI:Young Adult": "offline"},
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
        "Philadelphia City Institute" in item and "offline" in item for item in failures
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
        return_value=datetime(2026, 4, 1),
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
        return_value=datetime(2026, 10, 1),
    ):
        await coordinator._async_update_data()
    assert [call.args[1] for call in client.async_fetch_feed.await_args_list] == [
        "Young Adult",
        "Adult",
        "Senior",
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
            return_value=datetime(2026, 7, 18),
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
        return_value=datetime(2026, 7, 18),
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
            raise LibraryApiError("offline")
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
            return_value=datetime(2026, 7, 17),
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

    assert "Source coverage is unresolved" in response["message"]
    assert "Charles Santore Library — Young Adult" in response["message"]
    assert "offline" in response["message"]


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
        raise LibraryApiError("source unavailable")

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
        "SWK:Toddler": "source unavailable",
        "SWK:Preschool": "source unavailable",
        "SWK:School Age": "source unavailable",
        "SWK:Young Adult": "source unavailable",
    }
    assert list(data.source_statuses) == ["SWK:Baby"]


async def test_coordinator_rejects_complete_source_failure(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    client = types.SimpleNamespace(
        async_fetch_feed=AsyncMock(side_effect=LibraryApiError("offline"))
    )
    coordinator = LibraryDataCoordinator(
        hass,
        entry,
        client,
        (BRANCHES["SWK"],),
        date(2025, 1, 15),
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
