"""Native Home Assistant integration for Free Library events."""

from __future__ import annotations

import logging
import mimetypes
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

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
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .api import LibraryClient
from .config import entry_config, migrated_entry_config, selected_branches
from .const import (
    ATTR_EMBED_IMAGES,
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
    source_expansion_details,
    source_keys_for_window,
    source_label,
    supplemental_coverage,
)
from .digest import (
    BRANCHES,
    build_digest,
    event_identity,
    next_week_start,
    select_digest_events,
)
from .email_images import (
    EMAIL_IMAGE_DIRECTORY,
    IMAGE_CACHE_TTL_SECONDS,
    async_download_event_images,
    purge_stale_image_runs,
    purge_stored_image_runs,
    remove_stored_image_run,
    store_downloaded_images,
)
from .runtime import LibraryConfigEntry
from .webcal import async_register_webcal_view

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
        vol.Optional(ATTR_EMBED_IMAGES, default=False): cv.boolean,
    }
)


def _referenced_embedded_image_paths(
    rendered_html: str, image_paths: tuple[str, ...]
) -> tuple[str, ...]:
    """Return only stored CID images referenced by the final email HTML."""

    return tuple(
        path for path in image_paths if f'src="cid:{Path(path).name}"' in rendered_html
    )


def _email_image_storage(hass: HomeAssistant) -> tuple[Path, str | None]:
    """Return a Local Media-backed image root and its source directory ID."""

    if hass.config.media_dirs:
        source_directory_id = (
            "local"
            if "local" in hass.config.media_dirs
            else min(hass.config.media_dirs)
        )
        return (
            Path(hass.config.media_dirs[source_directory_id]) / EMAIL_IMAGE_DIRECTORY,
            source_directory_id,
        )
    return Path(hass.config.path("www", EMAIL_IMAGE_DIRECTORY)), None


def _smtp_attachments(
    image_paths: tuple[str, ...],
    *,
    image_root: Path,
    source_directory_id: str | None,
) -> list[dict[str, object]]:
    """Build smtp.send_message attachment objects for referenced CID images."""

    if source_directory_id is None:
        return []
    attachments: list[dict[str, object]] = []
    for image_path in image_paths:
        path = Path(image_path)
        try:
            relative_path = Path(EMAIL_IMAGE_DIRECTORY) / path.relative_to(image_root)
        except ValueError:
            continue
        attachments.append(
            {
                "media_source": {
                    "media_content_id": (
                        "media-source://media_source/"
                        f"{source_directory_id}/{relative_path.as_posix()}"
                    ),
                    "media_content_type": (
                        mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    ),
                },
                "filename": path.name,
                "content_id": path.name,
            }
        )
    return attachments


async def async_setup(hass: HomeAssistant, config: dict[str, object]) -> bool:
    """Register the native response-returning digest action."""

    del config
    async_register_webcal_view(hass)
    image_root, _source_directory_id = _email_image_storage(hass)
    legacy_image_root = Path(hass.config.path("www", EMAIL_IMAGE_DIRECTORY))
    for owned_root in {image_root, legacy_image_root}:
        await hass.async_add_executor_job(purge_stored_image_runs, owned_root)
    if not hass.services.has_service(DOMAIN, SERVICE_RENDER_DIGEST):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RENDER_DIGEST,
            _async_render_digest,
            schema=RENDER_DIGEST_SCHEMA,
            supports_response=SupportsResponse.ONLY,
        )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: LibraryConfigEntry) -> bool:
    """Split legacy combined settings into profile data and behavior options."""

    if entry.version != 1 or entry.minor_version > 2:
        return False
    if entry.minor_version == 2:
        return True
    try:
        data, options = migrated_entry_config(entry.data, entry.options)
    except TypeError, ValueError:
        _LOGGER.exception("Could not migrate the Free Library Events config entry")
        return False
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=1,
        minor_version=2,
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
            translation_domain=DOMAIN,
            translation_key="single_loaded_entry_required",
        )

    entry = loaded_entries[0]
    coordinator = entry.runtime_data
    if call.data[ATTR_FORCE_REFRESH]:
        await coordinator.async_request_refresh()
        if not coordinator.last_update_success:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="library_refresh_failed",
            )
    if coordinator.data is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="library_data_unavailable",
        )

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
    distance_by_branch_code: dict[str, float] = {}
    home_latitude = hass.config.latitude
    home_longitude = hass.config.longitude
    if home_latitude is not None and home_longitude is not None:
        for branch in branches:
            branch_distance = distance(
                home_latitude,
                home_longitude,
                branch.latitude,
                branch.longitude,
            )
            if branch_distance is not None:
                distance_by_branch_code[branch.code] = branch_distance
    image_url_overrides: dict[str, str] | None = None
    image_layout_overrides: dict[str, Literal["side", "hero"]] | None = None
    embedded_image_paths: tuple[str, ...] = ()
    image_download_count = 0
    image_download_failure_count = 0
    image_download_failure_examples: tuple[str, ...] = ()
    image_expires_at: str | None = None
    image_root, source_directory_id = _email_image_storage(hass)
    if call.data[ATTR_EMBED_IMAGES]:
        _weekly_events, included_events = select_digest_events(
            coordinator.data.events,
            birth_date=birth_date,
            filter_mode=config[CONF_FILTER_MODE],
            week_start=week_start,
            week_end=week_end,
        )
        included_events.sort(
            key=lambda event: (
                distance_by_branch_code.get(event.branch.code, float("inf")),
                event.starts_at,
                event.branch.name,
                event.title,
            )
        )
        download_batch = await async_download_event_images(
            async_get_clientsession(hass), included_events
        )
        image_download_count = download_batch.requested_count
        image_download_failure_count = download_batch.failure_count
        image_download_failure_examples = download_batch.failure_examples
        await hass.async_add_executor_job(
            purge_stale_image_runs,
            image_root,
            datetime.now(UTC).timestamp() - IMAGE_CACHE_TTL_SECONDS,
        )
        try:
            stored_images = await hass.async_add_executor_job(
                store_downloaded_images, image_root, download_batch
            )
        except OSError:
            image_download_failure_count = image_download_count
            image_download_failure_examples = (
                "Home Assistant could not store digest images",
            )
            stored_images = None
        fallback_urls = set(download_batch.fallback_urls)
        if stored_images is not None:
            render_urls = {
                **{source_url: source_url for source_url in fallback_urls},
                **stored_images.source_url_to_cid,
            }
            image_url_overrides = {
                event_identity(event): render_urls.get(event.image_url, "")
                for event in included_events
            }
            image_layout_overrides = {
                event_identity(event): (
                    "hero"
                    if stored_images.source_url_to_layout.get(event.image_url) == "hero"
                    else "side"
                )
                for event in included_events
            }
            embedded_image_paths = stored_images.paths
            run_directory = stored_images.run_directory
            if run_directory is not None:

                async def _async_remove_images(_now: datetime) -> None:
                    await hass.async_add_executor_job(
                        remove_stored_image_run, run_directory
                    )

                async_call_later(hass, IMAGE_CACHE_TTL_SECONDS, _async_remove_images)
                image_expires_at = (
                    datetime.now(UTC) + timedelta(seconds=IMAGE_CACHE_TTL_SECONDS)
                ).isoformat()
        if stored_images is None:
            fallback_urls.update(image.source_url for image in download_batch.images)
        if image_url_overrides is None:
            image_url_overrides = {
                event_identity(event): (
                    event.image_url if event.image_url in fallback_urls else ""
                )
                for event in included_events
            }
            image_layout_overrides = {
                event_identity(event): "side" for event in included_events
            }
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
        image_url_overrides=image_url_overrides,
        image_layout_overrides=image_layout_overrides,
        distance_by_branch_code=distance_by_branch_code,
    )
    metadata = cast(dict[str, Any], response["metadata"])
    metadata["expanded_capped_sources"] = source_expansion_details(coordinator.data)
    metadata["fetched_at"] = coordinator.data.fetched_at.isoformat()
    if call.data[ATTR_EMBED_IMAGES]:
        embedded_image_paths = _referenced_embedded_image_paths(
            cast(str, response["html"]), embedded_image_paths
        )
        response["images"] = list(embedded_image_paths)
        attachments = _smtp_attachments(
            embedded_image_paths,
            image_root=image_root,
            source_directory_id=source_directory_id,
        )
        response["attachments"] = attachments
        metadata["embedded_image_count"] = len(embedded_image_paths)
        metadata["smtp_attachment_count"] = len(attachments)
        metadata["image_download_count"] = image_download_count
        metadata["image_download_failure_count"] = image_download_failure_count
        metadata["image_download_failure_examples"] = list(
            image_download_failure_examples
        )
        metadata["image_expires_at"] = image_expires_at
    return cast(ServiceResponse, response)
