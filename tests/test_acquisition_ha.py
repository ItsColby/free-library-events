"""Acquisition retry and private diagnostic regression tests in real Home Assistant."""

from __future__ import annotations

import asyncio
import ssl
import types
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.free_library_events.api import (
    MAX_RSS_REQUEST_CONCURRENCY,
    MAX_RSS_RESPONSE_BYTES,
    OFFICIAL_EVENT_TYPES,
    SOURCE_ERROR_EXPANSION_TIMEOUT,
    SOURCE_ERROR_INVALID_FEED,
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
from custom_components.free_library_events.config import normalize_options
from custom_components.free_library_events.const import (
    CONF_BIRTH_DATE,
    CONF_BRANCHES,
    CONF_CHILD_NAME,
    CONF_PUBLISH_WEBCAL,
    CONF_WEBCAL_NAME,
    CONF_WEBCAL_TOKEN,
    CONFIG_ENTRY_MINOR_VERSION,
    DOMAIN,
)
from custom_components.free_library_events.coordinator import (
    MAX_TYPE_EXPANSIONS_PER_REFRESH,
    LibraryData,
    LibraryDataCoordinator,
    coverage_warnings,
    source_expansion_details,
    source_keys_for_window,
    supplemental_coverage,
    type_expansion_source_keys,
)
from custom_components.free_library_events.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.free_library_events.model import BRANCHES, Event
from custom_components.free_library_events.sensor import _build_status_projection
from tests.feed_support import empty_feed

LOCAL_TIME_ZONE = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    "name", ("Library\x00Calendar", "Library\x01Calendar", "Library\x7fCalendar")
)
def test_calendar_name_rejects_ics_control_characters(name: str) -> None:
    with pytest.raises(ValueError, match="invalid_webcal_name"):
        normalize_options({CONF_WEBCAL_NAME: name})


def test_calendar_name_normalizes_whitespace_and_preserves_unicode() -> None:
    options = normalize_options({CONF_WEBCAL_NAME: "  Bibliothèque\n\tCalendar  "})

    assert options[CONF_WEBCAL_NAME] == "Bibliothèque Calendar"


@pytest.mark.parametrize(
    "payload",
    (
        b"<html><body>Temporarily unavailable</body></html>",
        b"<error>Source unavailable</error>",
        b"<rss />",
        b"<rss><channel /><channel /></rss>",
    ),
)
async def test_non_feed_xml_cannot_report_successful_empty_coverage(
    payload: bytes,
) -> None:
    client = LibraryClient(Mock())
    client._async_get = AsyncMock(return_value=payload)

    with pytest.raises(LibraryApiError) as failure:
        await client.async_fetch_feed(BRANCHES["CEN"], "Baby")

    assert failure.value.category == SOURCE_ERROR_INVALID_FEED
    assert failure.value.retryable is False
    assert failure.value.__suppress_context__ is True


async def test_valid_empty_rss_retains_complete_coverage() -> None:
    client = LibraryClient(Mock())
    client._async_get = AsyncMock(return_value=b"<rss><channel /></rss>")

    feed = await client.async_fetch_feed(BRANCHES["CEN"], "Baby")

    assert feed.events == ()
    assert feed.source_count == feed.parsed_count == 0
    assert feed.covers_through(date(2026, 9, 20)) is True
    client._async_get.assert_awaited_once_with(BRANCHES["CEN"].rss_url_for_age("Baby"))


@pytest.mark.parametrize(
    ("error", "retryable"),
    (
        (
            aiohttp.ClientConnectorCertificateError(
                Mock(), ssl.CertificateError("synthetic certificate detail")
            ),
            False,
        ),
        (
            aiohttp.ClientConnectorSSLError(
                Mock(), ssl.SSLError("synthetic TLS detail")
            ),
            False,
        ),
        (
            aiohttp.ServerFingerprintMismatch(
                b"expected", b"received", "publisher.test", 443
            ),
            False,
        ),
        (aiohttp.ServerDisconnectedError("synthetic disconnect detail"), True),
        (TimeoutError("synthetic timeout detail"), True),
    ),
)
async def test_tls_policy_failures_do_not_receive_transport_retries(
    error: Exception, retryable: bool
) -> None:
    client = LibraryClient(Mock())
    client._async_get = AsyncMock(side_effect=error)

    with pytest.raises(LibraryApiError) as failure:
        await client.async_fetch_feed(BRANCHES["CEN"], "Baby")

    assert failure.value.category == SOURCE_ERROR_REQUEST_FAILED
    assert failure.value.retryable is retryable
    assert failure.value.__suppress_context__ is True
    assert failure.value.__cause__ is None
    assert str(failure.value) == SOURCE_ERROR_REQUEST_FAILED
    assert "synthetic" not in repr(failure.value)


async def test_malformed_redirect_is_a_sanitized_policy_failure() -> None:
    response = Mock(
        status=302,
        headers={"Location": "https://[synthetic-private-invalid-host/feed"},
    )
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = Mock()
    session.get.return_value = context
    client = LibraryClient(session)

    with pytest.raises(LibraryApiError) as failure:
        await client.async_fetch_feed(BRANCHES["CEN"], "Baby")

    assert failure.value.category == SOURCE_ERROR_UNSAFE_REDIRECT
    assert failure.value.retryable is False
    assert failure.value.__suppress_context__ is True
    assert session.get.call_count == 1


async def test_setup_failure_leaves_retry_scheduling_with_core(
    hass: HomeAssistant,
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)

    with patch(
        "custom_components.free_library_events.api.LibraryClient.async_fetch_feed",
        side_effect=LibraryApiError(SOURCE_ERROR_REQUEST_FAILED, retryable=True),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)

    coordinator = entry.runtime_data
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.retryable_failure_count == 5
    assert coordinator.last_attempt.expedited_retry_scheduled is False
    assert coordinator._setup_refresh_in_progress is False
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert coordinator.last_exception.retry_after is None
    entry.async_cancel_retry_setup()


@pytest.mark.parametrize("partial_recovery", (False, True))
async def test_first_nonretryable_failure_consumes_streak_retry_opportunity(
    hass: HomeAssistant, partial_recovery: bool
) -> None:
    entry = _entry()
    client = Mock(spec=LibraryClient)
    client.async_fetch_feed = AsyncMock(
        side_effect=LibraryApiError(SOURCE_ERROR_RESPONSE_TOO_LARGE)
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
    assert first_failure.value.retry_after is None

    client.async_fetch_feed.side_effect = LibraryApiError(
        SOURCE_ERROR_REQUEST_FAILED, retryable=True
    )
    with pytest.raises(UpdateFailed) as second_failure:
        await coordinator._async_update_data()
    assert second_failure.value.retry_after is None
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.retryable_failure_count == 5
    assert coordinator.last_attempt.expedited_retry_scheduled is False

    async def recover_feed(_branch, age_category):
        if partial_recovery and age_category != "Baby":
            raise LibraryApiError(SOURCE_ERROR_REQUEST_FAILED, retryable=True)
        return BranchFeed(
            events=(),
            age_category=age_category,
            source_count=0,
            parsed_count=0,
            last_event_date=None,
            ordered=True,
        )

    client.async_fetch_feed.side_effect = recover_feed
    await coordinator._async_update_data()
    assert coordinator.last_attempt.successful_source_count == (
        1 if partial_recovery else 5
    )

    client.async_fetch_feed.side_effect = LibraryApiError(
        SOURCE_ERROR_REQUEST_FAILED, retryable=True
    )
    with pytest.raises(UpdateFailed) as recovered_failure:
        await coordinator._async_update_data()
    assert recovered_failure.value.retry_after == 5 * 60
    assert coordinator.last_attempt.expedited_retry_scheduled is True


@pytest.mark.parametrize(
    "invalid_values",
    (
        {CONF_BIRTH_DATE: "synthetic private invalid date"},
        {CONF_WEBCAL_NAME: None},
    ),
)
async def test_diagnostics_remain_available_for_invalid_stored_configuration(
    hass: HomeAssistant, invalid_values: dict[str, object]
) -> None:
    entry = _entry(invalid_values)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["config"] is None
    assert result["config_error_category"] == "invalid_config"
    assert result["coordinator"]["last_update_success"] is None
    assert result["last_attempt"] is None
    assert result["sources"] == {}
    assert "synthetic private" not in repr(result)


async def test_diagnostics_redact_private_calendar_names(
    hass: HomeAssistant,
) -> None:
    entry = _entry(
        {
            CONF_WEBCAL_NAME: "Avery's private library calendar",
            CONF_PUBLISH_WEBCAL: True,
            CONF_WEBCAL_TOKEN: "synthetic-private-capability-token",
        }
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["config_error_category"] is None
    assert result["config"][CONF_WEBCAL_NAME] == "**REDACTED**"
    assert "Avery" not in repr(result)
    assert CONF_WEBCAL_TOKEN not in result["config"]
    assert "synthetic-private-capability-token" not in repr(result)


async def test_completion_wait_is_shared_and_caller_cancellation_is_isolated(
    hass: HomeAssistant,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    coordinator = _blocked_failure_coordinator(hass, started, release)
    first = asyncio.create_task(coordinator.async_request_refresh_and_wait())
    await started.wait()
    second = asyncio.create_task(coordinator.async_request_refresh_and_wait())
    await asyncio.sleep(0)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not second.done()
    assert coordinator._refresh_completion is not None
    assert not coordinator._refresh_completion.done()

    release.set()
    await second
    assert coordinator.last_update_success is False
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.failed_source_count == 5
    assert coordinator._refresh_completion is None
    await coordinator.async_shutdown()
    await hass.async_block_till_done()


async def test_completion_wait_fails_promptly_when_coordinator_unloads(
    hass: HomeAssistant,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    coordinator = _blocked_failure_coordinator(hass, started, release)
    pending = asyncio.create_task(coordinator.async_request_refresh_and_wait())
    await started.wait()

    await coordinator.async_shutdown()
    with pytest.raises(UpdateFailed) as failure:
        await pending
    assert failure.value.translation_key == "library_refresh_failed"
    assert coordinator._refresh_completion is None
    with pytest.raises(UpdateFailed):
        await coordinator.async_request_refresh_and_wait()
    assert coordinator._refresh_completion is None

    release.set()
    await hass.async_block_till_done()


async def test_completion_wait_timeout_does_not_cancel_source_refresh(
    hass: HomeAssistant,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    coordinator = _blocked_failure_coordinator(hass, started, release)

    with (
        patch(
            "custom_components.free_library_events.coordinator.REQUEST_REFRESH_TIMEOUT_SECONDS",
            0,
        ),
        pytest.raises(UpdateFailed) as failure,
    ):
        await coordinator.async_request_refresh_and_wait()
    assert failure.value.translation_key == "library_refresh_failed"
    await asyncio.wait_for(started.wait(), timeout=1)
    assert coordinator.last_attempt is None
    assert coordinator._refresh_completion is not None
    assert not coordinator._refresh_completion.done()

    release.set()
    await hass.async_block_till_done()
    assert coordinator.last_attempt is not None
    assert coordinator.last_attempt.failed_source_count == 5
    assert coordinator._refresh_completion is None
    await coordinator.async_shutdown()


def _blocked_failure_coordinator(
    hass: HomeAssistant, started: asyncio.Event, release: asyncio.Event
) -> LibraryDataCoordinator:
    async def fetch_feed(_branch, _age_category):
        started.set()
        await release.wait()
        raise LibraryApiError(SOURCE_ERROR_REQUEST_FAILED)

    client = Mock(spec=LibraryClient)
    client.async_fetch_feed = AsyncMock(side_effect=fetch_feed)
    return LibraryDataCoordinator(
        hass,
        _entry(),
        client,
        (BRANCHES["SWK"],),
        date(2025, 1, 15),
        timedelta(hours=6),
    )


def _entry(overrides: dict[str, object] | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CHILD_NAME: "Avery",
            CONF_BIRTH_DATE: "2025-01-15",
            CONF_BRANCHES: ["SWK"],
            **(overrides or {}),
        },
        version=1,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )


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
    assert expanded.expanded_through == date(2026, 7, 24)
    assert expanded.covers_through(date(2026, 7, 24))
    assert not expanded.covers_through(date(2026, 7, 25))

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
    assert "coverage is proven through July 24" in limitations[0]
    assert "proving coverage through July 26" in limitations[0]


@pytest.mark.parametrize(
    ("extra_blocker", "expected"),
    (
        (None, date(2026, 7, 27)),
        ("unordered", None),
        ("failed", None),
    ),
)
async def test_capped_type_shards_prove_through_the_earliest_capped_date(
    extra_blocker: str | None, expected: date | None
) -> None:
    branch = BRANCHES["CEN"]
    base_event = Event(
        title="Base event",
        event_date=date(2026, 7, 21),
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
    capped_last_dates = {
        "Community Events": date(2026, 7, 30),
        "Arts and Crafts Programs": date(2026, 7, 28),
    }

    async def fetch_single(_branch, age_category, event_type=None):
        if event_type == "Workshops and Enrichment" and extra_blocker == "failed":
            raise LibraryApiError(SOURCE_ERROR_REQUEST_FAILED)
        if event_type in capped_last_dates or (
            event_type == "Workshops and Enrichment" and extra_blocker
        ):
            return BranchFeed(
                events=(base_event,),
                age_category=age_category,
                source_count=10,
                parsed_count=10,
                last_event_date=capped_last_dates.get(event_type, date(2026, 7, 31)),
                ordered=event_type in capped_last_dates,
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
        branch, "Young Adult", base_feed, date(2026, 8, 2)
    )

    assert expanded.expanded_through == expected
    assert expanded.covers_through(date(2026, 7, 26)) is (expected is not None)
    assert not expanded.covers_through(date(2026, 8, 2))


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

    details = next(iter(source_expansion_details(data.source_statuses).values()))

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

    snapshot = LibraryData(
        events=(),
        source_counts={},
        source_statuses=data.source_statuses,
        source_errors={},
        fetched_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    projection = _build_status_projection(
        snapshot,
        None,
        True,
        date(2025, 11, 7),
        "Recommended",
        datetime(2026, 7, 18, tzinfo=LOCAL_TIME_ZONE),
    )
    data.source_statuses.clear()
    first = projection.attributes()["expanded_capped_sources"]
    assert next(iter(first.values())) == details
    first_details = next(iter(first.values()))
    first_details["type_feed_failure_examples"].clear()
    first_details["type_feed_blocker_examples"][0]["event_type"] = "Changed"
    second = projection.attributes()["expanded_capped_sources"]
    assert next(iter(second.values())) == details
    changed_hidden_blocker = replace(blockers[-1], event_type="Unexposed change")
    equivalent = _build_status_projection(
        replace(
            snapshot,
            source_statuses={
                "CEN:Young Adult": replace(
                    feed,
                    type_shard_blockers=(*blockers[:-1], changed_hidden_blocker),
                )
            },
        ),
        None,
        True,
        date(2025, 11, 7),
        "Recommended",
        datetime(2026, 7, 18, tzinfo=LOCAL_TIME_ZONE),
    )
    assert equivalent == projection


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
    assert source["type_feed_blockers"] == [
        {
            "event_type": f"Type {index}",
            "reason": TYPE_SHARD_BLOCKER_CAPPED,
            "published_item_count": 10,
            "parsed_item_count": 10,
            "last_event_date": "2026-07-24",
        }
        for index in range(4)
    ]
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

    session = types.SimpleNamespace(get=Mock(return_value=ResponseContext()))
    client = LibraryClient(session)

    with pytest.raises(LibraryApiError, match=SOURCE_ERROR_UNSAFE_REDIRECT):
        await client._async_get(
            "https://libwww.freelibrary.org/rss/eventsrss.cfm?location=CEN"
        )

    assert [request.args[0] for request in session.get.call_args_list] == [
        "https://libwww.freelibrary.org/rss/eventsrss.cfm?location=CEN",
    ]


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
        return empty_feed(age_category)

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


@pytest.mark.parametrize(
    ("evidence", "cause"),
    (
        ({"type_shard_failures": ("Storytime",)}, "expansion failed for 1"),
        (
            {
                "type_shard_blockers": (
                    TypeShardBlocker(
                        event_type="Storytime",
                        reason=TYPE_SHARD_BLOCKER_PARSE_INCOMPLETE,
                        source_count=4,
                        parsed_count=3,
                        last_event_date=date(2026, 7, 23),
                    ),
                )
            },
            "returned unusable evidence for 1",
        ),
        ({"type_shards_queried": 3}, "remained limited because"),
        ({}, "reached its 10-item limit through July 22"),
    ),
)
def test_coverage_warnings_name_the_unproven_date(
    evidence: dict[str, object], cause: str
) -> None:
    feed = BranchFeed(
        events=(),
        age_category="Baby",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 22),
        ordered=True,
        **evidence,
    )
    data = types.SimpleNamespace(source_statuses={"CEN:Baby": feed})

    warnings = coverage_warnings(
        data, date(2025, 1, 15), date(2026, 7, 20), date(2026, 7, 26)
    )

    assert len(warnings) == 1
    assert cause in warnings[0]
    assert warnings[0].endswith("; later events through July 26 may be missing")


def test_partial_expansion_proof_clears_only_the_weeks_it_covers() -> None:
    feed = BranchFeed(
        events=(),
        age_category="Baby",
        source_count=10,
        parsed_count=10,
        last_event_date=date(2026, 7, 21),
        ordered=True,
        type_shards_queried=len(OFFICIAL_EVENT_TYPES),
        type_shard_blockers=(
            TypeShardBlocker(
                event_type="Community Events",
                reason=TYPE_SHARD_BLOCKER_CAPPED,
                source_count=10,
                parsed_count=10,
                last_event_date=date(2026, 7, 27),
            ),
        ),
        base_prefix_recovered=True,
        expanded_through=date(2026, 7, 26),
    )
    data = types.SimpleNamespace(source_statuses={"CEN:Baby": feed})

    assert (
        coverage_warnings(data, date(2025, 1, 15), date(2026, 7, 20), date(2026, 7, 26))
        == []
    )
    (warning,) = coverage_warnings(
        data, date(2025, 1, 15), date(2026, 7, 27), date(2026, 8, 2)
    )
    assert "coverage is proven through July 26" in warning
    assert warning.endswith("; later events through August 2 may be missing")
