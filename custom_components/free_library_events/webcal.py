"""Token-protected dynamic iCalendar publishing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from hashlib import sha256
from http import HTTPStatus
import secrets
from urllib.parse import urlsplit, urlunsplit

from aiohttp import web

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .calendar_data import LibraryCalendarItem, build_calendar_items
from .config import entry_config
from .const import (
    CONF_PUBLISH_WEBCAL,
    CONF_SCAN_INTERVAL,
    CONF_WEBCAL_NAME,
    CONF_WEBCAL_TOKEN,
    DOMAIN,
    NAME,
)
from .runtime import LibraryConfigEntry

WEBCAL_PATH = f"/api/{DOMAIN}/calendar/{{token}}.ics"
DATA_WEBCAL_VIEW_REGISTERED = f"{DOMAIN}_webcal_view_registered"
ICALENDAR_PRODID = "-//ItsColby//Free Library Events for Home Assistant//EN"


@dataclass(frozen=True, slots=True)
class WebcalSubscriptionUrls:
    """Subscription URL variants and their Home Assistant URL scope."""

    http_url: str
    webcal_url: str
    external_url_configured: bool


def async_register_webcal_view(hass: HomeAssistant) -> None:
    """Register the process-lifetime calendar feed route once."""

    if hass.data.get(DATA_WEBCAL_VIEW_REGISTERED):
        return
    hass.http.register_view(FreeLibraryEventsCalendarFeedView)
    hass.data[DATA_WEBCAL_VIEW_REGISTERED] = True


def webcal_subscription_urls(hass: HomeAssistant, token: str) -> WebcalSubscriptionUrls:
    """Return canonical and convenience URLs without overstating reachability."""

    external_url_configured = True
    try:
        base_url = get_url(
            hass,
            allow_internal=False,
            allow_external=True,
            allow_cloud=True,
            prefer_external=True,
        )
    except NoURLAvailableError:
        external_url_configured = False
        base_url = get_url(
            hass,
            allow_internal=True,
            allow_external=False,
            allow_cloud=False,
            prefer_external=False,
        )
    http_url = f"{base_url.rstrip('/')}{WEBCAL_PATH.format(token=token)}"
    parsed = urlsplit(http_url)
    webcal_url = urlunsplit(("webcal", parsed.netloc, parsed.path, "", ""))
    return WebcalSubscriptionUrls(
        http_url=http_url,
        webcal_url=webcal_url,
        external_url_configured=external_url_configured,
    )


def webcal_subscription_url(hass: HomeAssistant, token: str) -> str:
    """Return the convenience WebCal subscription URL."""

    return webcal_subscription_urls(hass, token).webcal_url


def webcal_status(hass: HomeAssistant, enabled: bool, token: object) -> str:
    """Return a safe options-flow status without logging the token."""

    if not enabled or not isinstance(token, str) or not token:
        return "Disabled"
    try:
        urls = webcal_subscription_urls(hass, token)
    except NoURLAvailableError:
        return "Enabled; configure a Home Assistant URL to copy the feed address"
    scope = (
        "external/cloud URL" if urls.external_url_configured else "internal URL only"
    )
    return f"Enabled ({scope}): {urls.webcal_url}"


class FreeLibraryEventsCalendarFeedView(HomeAssistantView):
    """Serve the latest age-filtered coordinator cache as iCalendar."""

    url = WEBCAL_PATH
    name = f"api:{DOMAIN}:calendar"
    requires_auth = False

    async def get(self, request: web.Request, token: str) -> web.Response:
        """Return a calendar only when the opaque capability token matches."""

        return _calendar_response(request, token)

    async def head(self, request: web.Request, token: str) -> web.Response:
        """Return the same metadata as GET without transferring the calendar."""

        return _calendar_response(request, token)


def _calendar_response(request: web.Request, token: str) -> web.Response:
    """Build a cache-aware calendar response for GET or HEAD."""

    hass: HomeAssistant = request.app[KEY_HASS]
    entry = _loaded_entry_for_token(hass, token)
    if entry is None:
        raise web.HTTPNotFound
    coordinator = entry.runtime_data
    if coordinator.data is None:
        raise web.HTTPServiceUnavailable(headers={"Retry-After": "300"})

    config = entry_config(entry.data, entry.options)
    body = render_icalendar(
        build_calendar_items(coordinator.data.events, config),
        fetched_at=coordinator.data.fetched_at,
        refresh_seconds=int(config[CONF_SCAN_INTERVAL]),
        calendar_name=str(config[CONF_WEBCAL_NAME]),
    ).encode("utf-8")
    last_modified = _as_utc_second(coordinator.data.fetched_at)
    etag = f'"{sha256(body).hexdigest()}"'
    cache_headers = {
        "Cache-Control": "private, max-age=300, must-revalidate",
        "ETag": etag,
        "Last-Modified": format_datetime(last_modified, usegmt=True),
    }
    if _is_not_modified(request, etag, last_modified):
        return web.Response(status=HTTPStatus.NOT_MODIFIED, headers=cache_headers)

    return web.Response(
        body=body,
        status=HTTPStatus.OK,
        headers={
            **cache_headers,
            "Content-Disposition": 'inline; filename="free-library-events.ics"',
            "Content-Type": "text/calendar; charset=utf-8",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _as_utc_second(value: datetime) -> datetime:
    """Normalize a coordinator timestamp for HTTP date comparisons."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def _is_not_modified(request: web.Request, etag: str, last_modified: datetime) -> bool:
    """Apply RFC conditional-request precedence for a safe read-only feed."""

    if_none_match = request.headers.get("If-None-Match")
    if if_none_match is not None:
        return any(
            candidate == "*" or candidate.removeprefix("W/") == etag
            for candidate in (value.strip() for value in if_none_match.split(","))
        )
    modified_since = request.if_modified_since
    if modified_since is None:
        return False
    return _as_utc_second(modified_since) >= last_modified


def _loaded_entry_for_token(
    hass: HomeAssistant, candidate: str
) -> LibraryConfigEntry | None:
    """Find the loaded feed entry without revealing token validity details."""

    for entry in hass.config_entries.async_entries(DOMAIN):
        configured = entry.options.get(CONF_WEBCAL_TOKEN)
        if (
            entry.state is ConfigEntryState.LOADED
            and entry.options.get(CONF_PUBLISH_WEBCAL) is True
            and isinstance(configured, str)
            and configured
            and secrets.compare_digest(
                configured.encode("utf-8"), candidate.encode("utf-8")
            )
        ):
            return entry
    return None


def render_icalendar(
    items: Sequence[LibraryCalendarItem],
    *,
    fetched_at: datetime,
    refresh_seconds: int,
    calendar_name: str = NAME,
) -> str:
    """Serialize calendar items as deterministic RFC 5545 content."""

    stamp = _format_utc(fetched_at)
    refresh_duration = _format_duration(refresh_seconds)
    lines = [
        "BEGIN:VCALENDAR",
        f"PRODID:{ICALENDAR_PRODID}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_text(calendar_name)}",
        "X-WR-TIMEZONE:America/New_York",
        f"REFRESH-INTERVAL;VALUE=DURATION:{refresh_duration}",
        f"X-PUBLISHED-TTL:{refresh_duration}",
    ]
    for item in sorted(
        items, key=lambda value: (value.start, value.summary, value.uid)
    ):
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:{_escape_text(item.uid)}@free-library-events.home-assistant",
                f"DTSTAMP:{stamp}",
                f"LAST-MODIFIED:{stamp}",
                f"DTSTART:{_format_utc(item.start)}",
                f"DTEND:{_format_utc(item.end)}",
                f"SUMMARY:{_escape_text(item.summary)}",
                f"DESCRIPTION:{_escape_text(item.description)}",
                f"LOCATION:{_escape_text(item.location)}",
                f"URL:{_safe_uri(item.url)}",
                "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT",
                "SEQUENCE:0",
                "END:VEVENT",
            )
        )
    lines.append("END:VCALENDAR")
    physical_lines = [physical for line in lines for physical in _fold_line(line)]
    return "\r\n".join(physical_lines) + "\r\n"


def _format_utc(value: datetime) -> str:
    """Format a datetime as an iCalendar UTC timestamp."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _format_duration(seconds: int) -> str:
    """Format the configured polling interval as an RFC duration."""

    if seconds % 3600 == 0:
        return f"PT{seconds // 3600}H"
    if seconds % 60 == 0:
        return f"PT{seconds // 60}M"
    return f"PT{seconds}S"


def _escape_text(value: str) -> str:
    """Escape an RFC 5545 TEXT property value."""

    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _safe_uri(value: str) -> str:
    """Prevent source data from injecting another content line."""

    return value.replace("\r", "").replace("\n", "")


def _fold_line(line: str) -> tuple[str, ...]:
    """Fold one content line without splitting a UTF-8 code point."""

    folded: list[str] = []
    current = ""
    current_octets = 0
    content_limit = 75
    for character in line:
        character_octets = len(character.encode("utf-8"))
        if current and current_octets + character_octets > content_limit:
            folded.append(current if not folded else f" {current}")
            current = character
            current_octets = character_octets
            content_limit = 74
        else:
            current += character
            current_octets += character_octets
    folded.append(current if not folded else f" {current}")
    return tuple(folded)
