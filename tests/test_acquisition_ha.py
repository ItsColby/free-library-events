"""Acquisition retry and private diagnostic regression tests in real Home Assistant."""

from __future__ import annotations

import asyncio
import ssl
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.free_library_events.api import (
    SOURCE_ERROR_INVALID_FEED,
    SOURCE_ERROR_REQUEST_FAILED,
    SOURCE_ERROR_RESPONSE_TOO_LARGE,
    SOURCE_ERROR_UNSAFE_REDIRECT,
    BranchFeed,
    LibraryApiError,
    LibraryClient,
)
from custom_components.free_library_events.config import normalize_options
from custom_components.free_library_events.const import (
    CONF_BIRTH_DATE,
    CONF_BRANCHES,
    CONF_CHILD_NAME,
    CONF_PUBLISH_WEBCAL,
    CONF_WEBCAL_NAME,
    CONF_WEBCAL_TOKEN,
    DOMAIN,
)
from custom_components.free_library_events.coordinator import LibraryDataCoordinator
from custom_components.free_library_events.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.free_library_events.digest import BRANCHES

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


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
    )
