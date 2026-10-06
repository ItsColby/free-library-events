"""Email and calendar presentation for Free Library event digests."""

from __future__ import annotations

import html
import re
import urllib.parse
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from itertools import groupby

from .model import (
    AGE_CATEGORY_ORDER,
    EN_DASH,
    TIMEZONE,
    Branch,
    Event,
    HTMLDescriptionSanitizer,
    event_identity,
    format_age,
    format_event_time,
    has_positive_claim,
)

MIDDLE_DOT = "\N{MIDDLE DOT}"
MAX_DISPLAY_TITLE_LENGTH = 180
MAX_CALENDAR_DETAILS_CHARS = 1_200
MAX_CALENDAR_URL_LENGTH = 4_096
MAX_EVENT_CHIPS = 5
EMAIL_CONTENT_WIDTH = 680
EMAIL_POSTER_IMAGE_WIDTH = 440


def icon_for(event: Event) -> str:
    text = event.title.lower()
    if re.search(r"\b(?:read(?:ing)?|story(?:time)?|books?)\b", text):
        return "\U0001f4da"
    if re.search(r"\b(?:music|sing(?:ing)?|karaoke)\b", text):
        return "\U0001f3b5"
    if re.search(r"\b(?:crafts?|origami|art)\b", text):
        return "\U0001f3a8"
    if re.search(r"\b(?:playgroup|play group|playtime)\b", text):
        return "\U0001f9f8"
    return "\N{SPARKLES}"


_CONDITIONAL_LOCATION_LABEL = "Location depends on weather"
_CONDITIONAL_LOCATION_DETAILS = (
    f"{_CONDITIONAL_LOCATION_LABEL}; check the official listing"
)
_WEATHER_LOCATION_CONDITION_RE = re.compile(
    r"\b(?:cooler|warmer) weather\b|"
    r"\b(?:if|when|in(?: case of)?|during)\s+(?:the\s+)?"
    r"(?:(?:unfavorable|inclement|bad|rainy|cold|hot|wet)\s+)?weather\b|"
    r"\b(?:depending on|based on) (?:the )?weather\b|"
    r"\bif it rains\b|\bin case of rain\b",
    re.IGNORECASE,
)
_WEATHER_LOCATION_SUBJECT = (
    r"(?:we(?:['\u2019]ll)?|it(?:['\u2019]ll)?|"
    r"(?:(?:the|this|our)\s+)?(?:program|event|storytime))"
)
_WEATHER_LOCATION_MOVE = (
    rf"\b{_WEATHER_LOCATION_SUBJECT}\s+(?:(?:will|may|might|could|can)\s+)?(?:be\s+)?"
    r"(?:moves?|moved|relocat(?:e|es|ed))\s+"
    r"(?:(?:the\s+)?(?:event|program|storytime)\s+)?"
    r"(?:indoors?|outdoors?|inside|outside|to|into)\b"
)
_WEATHER_LOCATION_SETTING = (
    rf"\b{_WEATHER_LOCATION_SUBJECT}\s+(?:(?:will|may|might|could|can)\s+)?"
    r"(?:meet|gather|stay|be|is|are|held|(?:take|takes) place|"
    r"have (?:the )?(?:storytime|program|event))\s+(?:held\s+)?"
    r"(?:indoors?|outdoors?|inside|outside|in|at)\b"
)


def event_location_note(event: Event) -> str:
    """Explain a conditional physical venue, excluding cancellation-only wording."""

    if event.modality == "online":
        return ""
    if event.weather_location_conditional:
        return f"{_CONDITIONAL_LOCATION_DETAILS} before traveling."
    for clause in re.split(
        r"[.!;\n]+|\b(?:but|however)\b",
        f"{event.title}\n{event.description}",
        flags=re.IGNORECASE,
    ):
        conditional_weather = _WEATHER_LOCATION_CONDITION_RE.search(clause)
        if not (
            conditional_weather or re.search(r"\bweather\b", clause, re.IGNORECASE)
        ) or re.search(r"\bregardless of (?:the )?weather\b", clause, re.IGNORECASE):
            continue
        if (
            conditional_weather
            and has_positive_claim(_WEATHER_LOCATION_SETTING, clause)
        ) or (
            (
                conditional_weather
                or re.search(r"\b(?:may|might|could)\b", clause, re.IGNORECASE)
            )
            and has_positive_claim(_WEATHER_LOCATION_MOVE, clause)
        ):
            return f"{_CONDITIONAL_LOCATION_DETAILS} before traveling."
    return ""


def event_location_name(event: Event) -> str:
    """Return a precise place name or an explicit online/conditional label."""

    if event.modality == "online":
        return "Online"
    if event_location_note(event):
        return _CONDITIONAL_LOCATION_LABEL
    return event.venue or event.branch.name


def event_location_label(event: Event) -> str:
    """Return a place/room label or explicit online/conditional location context."""

    location = event_location_name(event)
    if event.modality == "online":
        return location
    if event.room and not event_location_note(event):
        location = f"{location} {MIDDLE_DOT} {event.room}"
    if event.modality == "hybrid":
        location += f" {MIDDLE_DOT} Online option"
    return location


def event_location_summary(event: Event) -> str:
    """Return the visible venue, room, and off-site hosting context."""

    summary = event_location_label(event)
    if (event.venue or event_location_note(event)) and event.modality != "online":
        summary += f" {MIDDLE_DOT} Hosted by {event.branch.name}"
    return summary


def _event_location_html(event: Event) -> str:
    """Render map-linked physical context without linking virtual/host context."""

    location_pin = '<span aria-hidden="true">&#128205;</span>&nbsp;'
    if event.modality == "online":
        return f"{location_pin}{html.escape(event_location_name(event))}"

    physical_label = event_location_name(event)
    if event.room and not event_location_note(event):
        physical_label += f" {MIDDLE_DOT} {event.room}"
    directions = event_directions_url(event)
    if directions:
        rendered = (
            f'{location_pin}<a class="event-location-link" '
            f'href="{html.escape(directions, quote=True)}" '
            'style="display:inline-block;padding:5px 0;color:#202124;'
            "text-decoration:underline;"
            'text-decoration-color:#c4c7c5;text-underline-offset:3px">'
            f"{html.escape(physical_label)}</a>"
        )
    else:
        rendered = f"{location_pin}{html.escape(physical_label)}"

    if event.modality == "hybrid":
        rendered += f" {MIDDLE_DOT} Online option"
    if event.venue or event_location_note(event):
        rendered += f" {MIDDLE_DOT} Hosted by {html.escape(event.branch.name)}"
    return rendered


def event_calendar_location(event: Event) -> str:
    """Return a precise address or a truthful online/conditional location label."""

    if event.modality == "online":
        return "Online"
    if event_location_note(event):
        return _CONDITIONAL_LOCATION_DETAILS + (
            " (hybrid)" if event.modality == "hybrid" else ""
        )
    if event.venue:
        location = f"{event.venue}, Philadelphia, PA"
        return f"{location} (hybrid)" if event.modality == "hybrid" else location
    room = f", {event.room}" if event.room else ""
    location = f"{event.branch.name}{room}, {event.branch.address}"
    return f"{location} (hybrid)" if event.modality == "hybrid" else location


def related_link_lines(event: Event) -> list[str]:
    """Return plain-text equivalents for official links embedded in description."""

    unique_links = dict.fromkeys(
        (link.label, link.url) for link in event.description_links
    )
    return [f"Related: {label}: {url}" for label, url in unique_links]


def event_details_url(event: Event) -> str:
    """Return the event page or the closest official calendar fallback."""

    return event.link or event.branch.calendar_url


def google_calendar_url(
    event: Event,
    duration_minutes: int,
    *,
    compact: bool = False,
) -> str:
    """Return a bounded creation URL, or omit it if required context cannot fit."""

    end = event.end_at or event.starts_at + timedelta(minutes=duration_minutes)
    location_note = event_location_note(event)
    context_parts = (
        [location_note, f"Hosted by {event.branch.name}"] if location_note else []
    )
    required_parts = [f"Official event details: {event_details_url(event)}"]
    if event.end_at is None:
        required_parts.append(
            "No end time was found in the parsed feed. This link uses "
            f"{duration_minutes} minutes as a fallback; check the listing before saving."
        )
    parameters = {
        "action": "TEMPLATE",
        "text": bounded_text(event.title, MAX_DISPLAY_TITLE_LENGTH),
        "dates": f"{event.starts_at:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}",
        "ctz": TIMEZONE,
        "location": event_calendar_location(event),
        "details": "",
    }
    base = "https://calendar.google.com/calendar/render?"

    def render_url(description: str, links: Sequence[str] = ()) -> str:
        parameters["details"] = "\n\n".join(
            part
            for part in (*context_parts, description, *links, *required_parts)
            if part
        )
        return base + urllib.parse.urlencode(parameters)

    url = render_url("")
    if len(url) > MAX_CALENDAR_URL_LENGTH:
        return ""
    if compact:
        return url

    description = bounded_text(event.description, MAX_CALENDAR_DETAILS_CHARS)
    url = render_url(description)
    while len(url) > MAX_CALENDAR_URL_LENGTH and description:
        overflow = len(url) - MAX_CALENDAR_URL_LENGTH
        description = bounded_text(
            description, max(0, len(description) - overflow - 32)
        )
        url = render_url(description)
    links: list[str] = []
    for link in related_link_lines(event):
        candidate = render_url(description, (*links, link))
        if len(candidate) > MAX_CALENDAR_URL_LENGTH:
            break
        links.append(link)
        url = candidate
    return url


def _maps_search_url(query: str) -> str:
    return "https://www.google.com/maps/search/?" + urllib.parse.urlencode(
        {"api": "1", "query": query}
    )


def directions_url(branch: Branch) -> str:
    return _maps_search_url(f"{branch.name}, {branch.address}")


def event_directions_url(event: Event) -> str:
    """Return directions only when the physical destination is not conditional."""

    if event.modality == "online" or event_location_note(event):
        return ""
    if not event.venue:
        return directions_url(event.branch)
    return _maps_search_url(f"{event.venue}, Philadelphia, PA")


def bounded_text(value: str, maximum: int) -> str:
    """Shorten display text at a word boundary and mark the omission."""

    normalized = " ".join(value.split())
    if len(normalized) <= maximum:
        return normalized
    if maximum <= 1:
        return "" if maximum == 0 else "\N{HORIZONTAL ELLIPSIS}"
    clipped = normalized[: maximum - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (clipped or normalized[: maximum - 1]).rstrip() + "\N{HORIZONTAL ELLIPSIS}"


def _description_html(event: Event) -> str:
    """Render normalized text while restoring only validated source links."""

    parts: list[str] = []
    cursor = 0
    for link in event.description_links:
        start = -1
        search_from = 0
        for _ in range(link.occurrence + 1):
            start = event.description.find(link.label, search_from)
            if start < 0:
                break
            search_from = start + len(link.label)
        if start < cursor:
            continue
        parts.append(html.escape(event.description[cursor:start]))
        label = html.escape(link.label)
        anchor = (
            f'<a href="{html.escape(link.url, quote=True)}" '
            f"{HTMLDescriptionSanitizer._LINK_STYLE}>"
            f"{label}</a>"
        )
        parts.append(anchor)
        cursor = start + len(link.label)
    parts.append(html.escape(event.description[cursor:]))
    return "".join(parts)


def _description_paragraphs_html(event: Event) -> str:
    """Render sanitized rich HTML, with a plain-text fallback for older events."""

    if event.description_html:
        return event.description_html

    paragraphs = re.split(r"\n{2,}", _description_html(event).strip())
    rendered: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        if not paragraph:
            continue
        margin = "0" if index == len(paragraphs) - 1 else "0 0 12px"
        rendered.append(
            '<p class="event-description-paragraph" '
            f'style="margin:{margin};color:#3c4043;font-size:15px;line-height:160%">'
            f"{paragraph.replace(chr(10), '<br>')}</p>"
        )
    return "".join(rendered)


def _logistics_chip_specs(
    event: Event, searchable: str
) -> tuple[list[tuple[str, str]], bool]:
    """Return logistics chips and whether the event is a take-home craft."""

    logistics_chips: list[tuple[str, str]] = []
    if not event_location_note(event) and (
        has_positive_claim(r"\b(?:outdoor|outdoors|outside)\b", searchable)
        or (
            event.venue
            and re.search(
                r"\b(?:park|square|playground|garden)\b",
                event.venue,
                re.IGNORECASE,
            )
        )
    ):
        logistics_chips.append(("logistics", "Outdoors"))
    take_home_craft = has_positive_claim(
        r"\b(?:to-go|take[ -]home)\s+(?:a\s+)?craft\b", searchable
    )
    if take_home_craft:
        logistics_chips.append(("logistics", "Take-home craft"))
    if has_positive_claim(r"\bsiblings? (?:are )?welcome\b", searchable):
        logistics_chips.append(("logistics", "Siblings welcome"))
    if has_positive_claim(
        r"\b(?:kids|children) of all ages\b|\beven the littlest\b", searchable
    ):
        logistics_chips.append(("logistics", "All ages welcome"))
    elif (
        has_positive_claim(r"\brange of ages\b", searchable)
        and len(set(event.age_categories)) <= 1
    ):
        logistics_chips.append(("logistics", "Broad ages"))
    aac_board_provided = re.search(
        r"\b(?:receive|provided|given)[^.]{0,50}\bAAC boards?\b|"
        r"\bAAC boards?\b[^.]{0,50}\b(?:take home|provided)\b",
        searchable,
        re.IGNORECASE,
    )
    aac_board_negated = re.search(
        r"\bAAC boards?\b[^.]{0,35}\b(?:not|aren't|are not)\s+provided\b|"
        r"\b(?:no|without)\s+AAC boards?\b",
        searchable,
        re.IGNORECASE,
    )
    if aac_board_provided and not aac_board_negated:
        logistics_chips.append(("logistics", "AAC board provided"))
    return logistics_chips, take_home_craft


def event_chip_specs(event: Event) -> tuple[tuple[str, str], ...]:  # noqa: C901
    """Return bounded, prioritized highlights provable from publisher wording."""

    if event.display_highlights is not None:
        return event.display_highlights

    topic_chips: list[tuple[str, str]] = []
    action_chips: list[tuple[str, str]] = []
    searchable = f"{event.title}\n{event.description}"
    activity_rules = (
        (r"\bstorytimes?\b", r"\bstorytimes?\b", "Storytime"),
        (
            r"\bmusic program\b|\blive music\b|\bsing[ -]?along\b",
            r"\bmusic\b|\bsing[ -]?along\b",
            "Music",
        ),
        (r"\bplaygroups?\b", r"\bplaygroups?\b", "Playgroup"),
        (r"\bplaytimes?\b", r"\bplaytimes?\b", "Playtime"),
        (
            r"\b(?:crafts?|crafting|crafternoon)\b",
            r"\b(?:crafts?|crafting|crafternoon)\b",
            "Crafts",
        ),
        (r"\bAAC\b", r"\bAAC\b", "AAC"),
    )
    for source_pattern, title_pattern, label in activity_rules:
        if has_positive_claim(source_pattern, searchable) and not re.search(
            title_pattern, event.title, re.IGNORECASE
        ):
            topic_chips.append(("topic", label))
    logistics_chips, take_home_craft = _logistics_chip_specs(event, searchable)
    if take_home_craft:
        topic_chips = [chip for chip in topic_chips if chip != ("topic", "Crafts")]
    weather_risk = re.search(
        r"\bweather permitting\b|\bweather\b[^.]{0,60}\b(?:cancel|postpone|"
        r"reschedul)",
        searchable,
        re.IGNORECASE,
    )
    weather_conditions = re.search(
        r"\b(?:unfavorable|inclement) weather\b",
        searchable,
        re.IGNORECASE,
    )
    weather_negated = re.search(
        r"\bwill not be cancel(?:l)?ed (?:for|due to|because of) (?:the )?weather\b|"
        r"\b(?:does|do) not cancel (?:for|due to|because of) (?:the )?weather\b|"
        r"\bweather[^.]{0,35}\bwill not cancel\b|"
        r"\bregardless of (?:the )?weather\b",
        searchable,
        re.IGNORECASE,
    )
    if not weather_negated and (
        weather_risk or (weather_conditions and not event_location_note(event))
    ):
        action_chips.append(("action", "Weather dependent"))
    if re.search(r"\bwhile supplies last\b", searchable, re.IGNORECASE):
        action_chips.append(("action", "Limited supplies"))
    registration_required = re.search(
        r"\b(?:advance\s+)?registration\s+(?:is\s+)?required\b",
        searchable,
        re.IGNORECASE,
    )
    registration_not_required = re.search(
        r"\b(?:no registration|registration (?:is )?not required)\b",
        searchable,
        re.IGNORECASE,
    )
    registration_qualified = re.search(
        r"\bregistration\s+(?:is\s+)?required\s+for\s+(?:adults?|caregivers?)\s+only\b",
        searchable,
        re.IGNORECASE,
    )
    if (
        registration_required
        and not registration_not_required
        and not registration_qualified
    ):
        action_chips.append(("action", "Registration required"))

    if has_positive_claim(r"\b(?:drop[ -]?ins?|walk[ -]?ins? welcome)\b", searchable):
        logistics_chips.append(("logistics", "Drop-in"))
    if re.search(
        r"\b(?:materials?|supplies) (?:are |will be )?provided\b",
        searchable,
        re.IGNORECASE,
    ) and not re.search(
        r"\b(?:materials?|supplies) (?:are |will be )?not provided\b|"
        r"\bno (?:materials?|supplies) (?:are |will be )?provided\b",
        searchable,
        re.IGNORECASE,
    ):
        logistics_chips.append(("logistics", "Materials provided"))
    if has_positive_claim(
        r"\b(?:caregiver|parent|adult) (?:participation|participates?|joins?)\b|"
        r"\bwith (?:a |their )?(?:caregiver|parent|adult)\b",
        searchable,
    ):
        logistics_chips.append(("logistics", "Caregiver participation"))
    if has_positive_claim(r"\bsensory[ -]friendly\b", searchable):
        logistics_chips.append(("logistics", "Sensory-friendly"))
    if has_positive_claim(
        r"\bASL (?:interpretation|interpreter|interpreted)\b", searchable
    ):
        logistics_chips.append(("logistics", "ASL interpreted"))
    if has_positive_claim(
        r"\bbilingual\b|\b(?:English|Spanish)\s*(?:and|/)\s*(?:English|Spanish)\b",
        searchable,
    ):
        logistics_chips.append(("logistics", "Bilingual"))

    action_priority = {
        "Registration required": 0,
        "Weather dependent": 1,
        "Limited supplies": 3,
    }
    action_chips.sort(key=lambda chip: action_priority.get(chip[1], 99))
    ordered = action_chips + logistics_chips + topic_chips
    return tuple(dict.fromkeys(ordered))[:MAX_EVENT_CHIPS]


def _event_chips_html(event: Event) -> str:
    colors = {
        "topic": "#1c6984",
        "logistics": "#477a00",
        "action": "#cf102d",
    }
    chips = "".join(
        '<span style="display:inline-block;margin:4px 5px 0 0;padding:4px 7px;'
        f"border-radius:5px;background:{colors[kind]};color:#ffffff;"
        'font-size:12px;font-weight:800">'
        f"{html.escape(label)}</span>"
        for kind, label in event_chip_specs(event)
    )
    return (
        f'<div class="event-highlights" style="margin:8px 0 0">{chips}</div>'
        if chips
        else ""
    )


def event_age_categories(event: Event) -> tuple[str, ...]:
    """Return every published age category in stable display order."""

    return tuple(
        sorted(
            dict.fromkeys(event.age_categories),
            key=lambda category: AGE_CATEGORY_ORDER.get(
                category, len(AGE_CATEGORY_ORDER)
            ),
        )
    )


def _event_audience_html(event: Event) -> str:
    categories = event_age_categories(event)
    if not categories:
        return ""
    audience = f" {MIDDLE_DOT} ".join(html.escape(category) for category in categories)
    return (
        '<div class="event-audience" style="margin:10px 0 0;color:#5f6368;'
        'font-size:14px;line-height:145%"><strong>Library age listing:</strong> '
        f"{audience}</div>"
    )


def _button(label: str, url: str) -> str:
    return (
        '<table class="email-button" role="presentation" border="0" '
        'cellpadding="0" cellspacing="0" '
        'style="border-collapse:separate;margin:12px 0 0">'
        '<tr><td class="email-button-cell" bgcolor="#1967d2" '
        'style="padding:13px 16px;'
        'border:1px solid #1967d2;border-radius:8px;background:#1967d2">'
        f'<a class="email-button-link" href="{html.escape(url, quote=True)}" '
        'style="display:block;'
        "color:#ffffff;font-weight:700;text-decoration:none;font-size:15px;"
        f'line-height:140%">{html.escape(label)}</a></td></tr></table>'
    )


def _branch_calendar_links_html(branches: Sequence[Branch]) -> str:
    """Render branch calendars as an email-safe two-column link grid."""

    rows: list[str] = []
    for index in range(0, len(branches), 2):
        cells: list[str] = []
        for branch in branches[index : index + 2]:
            label = branch.name.replace(" Library", "")
            cells.append(
                '<td class="branch-calendar-cell" width="50%" valign="top" '
                'style="width:50%;padding:4px">'
                f'<a class="branch-calendar-link" '
                f'href="{html.escape(branch.calendar_url, quote=True)}" '
                'style="display:block;padding:10px;border:1px solid #c4c7c5;'
                "border-radius:8px;color:#174ea6;font-size:14px;font-weight:700;"
                'line-height:145%;text-align:center;text-decoration:none">'
                f"{html.escape(label)}</a></td>"
            )
        if len(cells) == 1:
            cells.append(
                '<td class="branch-calendar-empty" width="50%" '
                'style="width:50%;padding:4px">&nbsp;</td>'
            )
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<table class="branch-calendar-table" role="presentation" width="100%" '
        'border="0" cellpadding="0" cellspacing="0" '
        'style="width:100%;margin:8px 0 0;border-collapse:collapse">'
        f"{''.join(rows)}</table>"
    )


def _format_week_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start:%B} {start.day}{EN_DASH}{end.day}, {end.year}"
    return f"{start:%B} {start.day}{EN_DASH}{end:%B} {end.day}, {end.year}"


def subject_week_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start:%b} {start.day}{EN_DASH}{end.day}"
    return f"{start:%b} {start.day}{EN_DASH}{end:%b} {end.day}"


def _source_note(
    source_errors: Sequence[str],
    source_warnings: Sequence[str],
) -> str:
    """Return the shared source-coverage disclosure when listings may be missing."""

    if source_warnings or source_errors:
        return (
            "Some feed requests failed or have unresolved coverage limits. "
            "Use the official branch calendars to check for other events."
        )
    return ""


def _calendar_placeholder_note(
    events: Sequence[Event],
    duration_minutes: int,
    *,
    calendar_link_ids: frozenset[str] | None = None,
) -> str:
    """Return one precise note for Google links that need placeholder end times."""

    linked_events = [
        event
        for event in events
        if (
            event_identity(event) in calendar_link_ids
            if calendar_link_ids is not None
            else bool(google_calendar_url(event, duration_minutes, compact=True))
        )
    ]
    missing_count = sum(event.end_at is None for event in linked_events)
    if not missing_count:
        return ""
    if missing_count == len(events):
        opening = "No end time was found in the fetched data for these events"
    else:
        opening = "No end time was found in the fetched data for some events"
    return (
        f"{opening}. Their Google Calendar links use a {duration_minutes}-minute "
        "fallback duration; check the listing before saving."
    )


def _email_omission_note(omitted_count: int) -> str:
    """Disclose email-only omissions identically in either body format."""

    return (
        f"To stay within the email size limit, {omitted_count} matched "
        f"activit{'y was' if omitted_count == 1 else 'ies were'} omitted. "
        "Check the official branch calendars for more events."
    )


def render_event_card(
    event: Event,
    *,
    duration_minutes: int,
    compact: bool = False,
) -> str:
    event_url = html.escape(event_details_url(event), quote=True)
    display_title = bounded_text(event.title, MAX_DISPLAY_TITLE_LENGTH)
    calendar_url = google_calendar_url(event, duration_minutes, compact=compact)
    location_html = _event_location_html(event)
    if compact:
        calendar_link = (
            '<div class="compact-calendar-link" style="margin:8px 0 0;'
            'font-size:14px;font-weight:700;line-height:145%">'
            f'<a href="{html.escape(calendar_url, quote=True)}" '
            'style="display:inline-block;padding:5px 0;color:#1967d2;'
            'text-decoration:underline">Add to Google Calendar</a></div>'
            if calendar_url
            else ""
        )
        return f"""
    <table class="event-card-shell compact-event-card" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">
    <tr><td bgcolor="#ffffff" style="padding:14px 18px 15px;background:#ffffff;border:1px solid #e3e7ee;border-radius:12px;overflow-wrap:anywhere;word-break:break-word">
      <h3 class="event-title" style="margin:0 0 5px;color:#202124;font-size:19px;line-height:130%"><span aria-hidden="true">{icon_for(event)}</span> <a href="{event_url}" style="color:#174ea6;text-decoration:underline">{html.escape(display_title)}</a></h3>
      <div class="event-meta" style="font-size:14px;font-weight:700;color:#202124;line-height:145%">
        <div class="event-time">{format_event_time(event)}</div>
        <div class="event-location" style="margin:2px 0 0">{location_html}</div>
      </div>
      {_event_audience_html(event)}
      {_event_chips_html(event)}
      {calendar_link}
    </td></tr><tr><td height="10" style="height:10px;font-size:1px;line-height:10px">&nbsp;</td></tr>
    </table>
    """
    event_image = ""
    if event.image_url and event.image_layout == "hero":
        event_image = (
            '<tr><td class="event-hero-image-cell" colspan="2" style="padding:0;'
            'background:#ffffff;text-align:center">'
            f'<a href="{event_url}" style="display:block;width:100%;text-decoration:none">'
            f'<img width="{EMAIL_CONTENT_WIDTH}" '
            f'src="{html.escape(event.image_url, quote=True)}" '
            f'alt="View official event details for {html.escape(display_title, quote=True)}" '
            'style="display:block;width:100%;max-width:100%;height:auto;margin:0;'
            'border:0;border-radius:13px 13px 0 0"></a></td></tr>'
        )
    elif event.image_url:
        event_image = (
            '<tr><td class="event-poster-image-cell" colspan="2" '
            'style="padding:0;background:#ffffff;text-align:center">'
            f'<a href="{event_url}" style="display:block;width:100%;'
            'text-decoration:none">'
            f'<img width="{EMAIL_POSTER_IMAGE_WIDTH}" align="center" '
            f'src="{html.escape(event.image_url, quote=True)}" '
            f'alt="View official event details for '
            f'{html.escape(display_title, quote=True)}" '
            f'style="display:block;width:100%;max-width:{EMAIL_POSTER_IMAGE_WIDTH}px;'
            'height:auto;margin:0 auto;border:0;border-radius:13px 13px 0 0">'
            "</a></td></tr>"
        )
    shortened_note = ""
    if event.description_truncated:
        shortened_note = (
            f'<p style="margin:8px 0 0;color:#5f6368;font-size:13px;line-height:150%">'
            f'Description excerpt. <a href="{event_url}" '
            'style="color:#174ea6">Read the full listing</a>.</p>'
        )
    body = f"""
      <tr>
      <td class="event-body-cell" colspan="2" style="padding:16px 20px 18px;border-top:1px solid #eef1f5;overflow-wrap:anywhere;word-break:break-word">
        <div>{_description_paragraphs_html(event)}</div>
        {shortened_note}
        {_button("Add to Google Calendar", calendar_url) if calendar_url else ""}
      </td>
      </tr>"""
    return f"""
    <table class="event-card-shell" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">
    <tr><td style="padding:0 0 12px">
      <table class="event-card-table" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#ffffff" style="width:100%;border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #e3e7ee;border-radius:14px;overflow:hidden">
      {event_image}
      <tr>
      <td class="event-heading-cell" colspan="2" valign="top" style="padding:16px 20px 14px;overflow-wrap:anywhere;word-break:break-word">
        <h3 class="event-title" style="margin:0 0 6px;color:#202124;font-size:22px;line-height:125%"><span aria-hidden="true">{icon_for(event)}</span> <a href="{event_url}" style="color:#174ea6;text-decoration:underline;text-decoration-color:#a8c7fa;text-underline-offset:3px">{html.escape(display_title)}</a></h3>
        <div class="event-meta" style="font-size:16px;font-weight:700;color:#202124;line-height:145%">
          <div class="event-time">{format_event_time(event)}</div>
          <div class="event-location" style="margin:2px 0 0">{location_html}</div>
        </div>
        {_event_audience_html(event)}
        {_event_chips_html(event)}
      </td>
      </tr>
      {body}
      </table>
    </td></tr>
    </table>
    """


def render_html(  # noqa: C901
    events: Sequence[Event],
    *,
    child_name: str,
    birth_date: date,
    week_start: date,
    week_end: date,
    branches: Sequence[Branch],
    duration_minutes: int,
    source_errors: Sequence[str],
    source_warnings: Sequence[str],
    full_event_ids: frozenset[str] | None = None,
    email_omitted_count: int = 0,
    rendered_cards: Mapping[tuple[Event, bool], str] | None = None,
    calendar_link_ids: frozenset[str] | None = None,
) -> str:
    if full_event_ids is None:
        full_event_ids = frozenset(event_identity(event) for event in events)
    if calendar_link_ids is None:
        calendar_link_ids = frozenset(
            event_identity(event)
            for event in events
            if google_calendar_url(event, duration_minutes, compact=True)
        )
    day_sections: list[str] = []
    for event_date, day_items in groupby(events, key=lambda event: event.event_date):
        day_cards = "".join(
            (
                rendered_cards[(event, event_identity(event) not in full_event_ids)]
                if rendered_cards is not None
                else render_event_card(
                    event,
                    duration_minutes=duration_minutes,
                    compact=event_identity(event) not in full_event_ids,
                )
            )
            for event in day_items
        )
        day_sections.append(
            f"""
            <table class="event-day-heading" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">
              <tr><td style="padding:0 4px 10px"><h2 class="event-day-title" style="margin:0;color:#174ea6;font-size:20px;font-weight:800;line-height:130%">{event_date:%A, %B} {event_date.day}</h2></td></tr>
            </table>
            {day_cards}
            <table class="event-day-spacer" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">
              <tr><td height="12" style="height:12px;font-size:1px;line-height:12px">&nbsp;</td></tr>
            </table>
            """
        )

    if day_sections:
        body = "".join(day_sections)
        activity_noun = "activity" if len(events) == 1 else "activities"
        event_branch_count = len({event.branch.code for event in events})
        library_noun = "library" if event_branch_count == 1 else "libraries"
        branch_preposition = "at" if event_branch_count == 1 else "across"
        intro = (
            f"{len(events)} {activity_noun} selected for {child_name} "
            f"{branch_preposition} {event_branch_count} {library_noun}."
        )
        if len(full_event_ids) < len(events):
            intro += " Some entries use shorter cards to fit this email."
            if not email_omitted_count:
                intro += " Every matched event is included."
    else:
        intro = (
            f"This digest has no matching events for {child_name}, "
            f"age {format_age(birth_date, week_start)}, for the dates above."
        )
        body = (
            '<div style="padding:20px;background:#ffffff;border:1px solid #e3e7ee;'
            'border-radius:14px;color:#3c4043">The fetched data and current matching '
            "rules produced no entries. Check the official branch calendars below "
            "for events to consider.</div>"
        )

    branch_links = _branch_calendar_links_html(branches)
    source_note_parts: list[str] = []
    if note := _source_note(source_errors, source_warnings):
        source_note_parts.append(
            f'<p style="margin:8px 0 0;color:#b3261e">{html.escape(note)}</p>'
        )
    if email_omitted_count:
        source_note_parts.append(
            '<p style="margin:8px 0 0;color:#5f6368">'
            f"{_email_omission_note(email_omitted_count)}</p>"
        )
    source_note = "".join(source_note_parts)
    calendar_note_text = _calendar_placeholder_note(
        events, duration_minutes, calendar_link_ids=calendar_link_ids
    )
    calendar_note = ""
    if calendar_note_text:
        calendar_note = (
            '<p style="margin:8px 0 0;color:#5f6368">'
            f"{html.escape(calendar_note_text)}</p>"
        )
    if events:
        first_event_date = events[0].event_date
        last_event_date = events[-1].event_date
        event_day_range = f"{first_event_date:%A}"
        if first_event_date != last_event_date:
            event_day_range += f"{EN_DASH}{last_event_date:%A}"
        event_branch_count = len({event.branch.code for event in events})
        library_noun = "library" if event_branch_count == 1 else "libraries"
        preheader_features = []
        if any(
            event.image_url and event_identity(event) in full_event_ids
            for event in events
        ):
            preheader_features.append("photos")
        if any(event.age_categories for event in events):
            preheader_features.append("age notes")
        if any(event_directions_url(event) for event in events):
            preheader_features.append("directions")
        if any(event_identity(event) in calendar_link_ids for event in events):
            preheader_features.append("calendar links")
        if len(preheader_features) <= 2:
            feature_summary = " and ".join(preheader_features)
        else:
            feature_summary = (
                ", ".join(preheader_features[:-1]) + f", and {preheader_features[-1]}"
            )
        feature_suffix = f", with {feature_summary}" if feature_summary else ""
        preheader = f"{event_day_range} from {event_branch_count} {library_noun}{feature_suffix}."
    else:
        preheader = (
            "No matching entries in this digest. The official branch calendars "
            "can help you check for other events."
        )

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>Library fun for {html.escape(child_name)}</title>
<style>
html,body {{color-scheme:only light}}
@media only screen and (max-width:620px) {{
  .email-shell {{padding:12px 8px!important}}
  .email-header {{padding:20px 18px 18px!important}}
  .email-title {{font-size:27px!important;line-height:120%!important}}
  .email-content {{padding:18px 0!important}}
  .email-footer {{padding:16px!important;font-size:14px!important}}
  .event-day-title {{font-size:19px!important}}
  .event-poster-image-cell img {{width:100%!important;max-width:100%!important;height:auto!important;margin:0 auto!important}}
  .event-hero-image-cell img {{width:100%!important;max-width:100%!important;height:auto!important}}
  .event-heading-cell {{width:auto!important;max-width:none!important;padding:14px 14px 12px!important}}
  .event-title {{font-size:20px!important;line-height:125%!important}}
  .event-meta {{font-size:15px!important;line-height:145%!important}}
  .event-location-link {{display:inline-block!important;padding:13px 0!important}}
  .event-audience {{margin-top:8px!important;font-size:14px!important}}
  .event-highlights {{margin-top:6px!important}}
  .event-highlights span {{padding:5px 7px!important;font-size:13px!important}}
  .event-body-cell {{padding:15px 16px 17px!important}}
  .event-description-paragraph,.event-description-list {{font-size:16px!important;line-height:155%!important}}
  .email-button {{width:100%!important}}
  .email-button-cell {{padding:14px 16px!important;text-align:center!important}}
  .email-button-link {{font-size:16px!important;line-height:125%!important}}
  .compact-calendar-link a {{display:block!important;padding:13px 0!important;font-size:16px!important;line-height:135%!important}}
  .branch-calendar-link {{padding:13px 10px!important;font-size:15px!important}}
}}
@media only screen and (max-width:390px) {{
  .event-heading-cell {{padding:15px 16px 13px!important}}
  .branch-calendar-cell {{display:block!important;width:auto!important}}
  .branch-calendar-empty {{display:none!important}}
}}
</style></head>
<body style="margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#202124">
  <div style="display:none!important;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all">{html.escape(preheader)}&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;</div>
  <table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#f3f6fb" style="width:100%;border-collapse:collapse;background:#f3f6fb"><tr><td class="email-shell" align="center" style="padding:20px 10px">
    <table class="email-container" role="presentation" width="{EMAIL_CONTENT_WIDTH}" border="0" cellpadding="0" cellspacing="0" style="width:100%;max-width:{EMAIL_CONTENT_WIDTH}px;border-collapse:collapse">
      <tr><td class="email-header" style="padding:24px 24px 20px;background:#174ea6;border-radius:16px 16px 0 0;color:#ffffff">
        <div style="font-size:13px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;opacity:.85">{_format_week_range(week_start, week_end)}</div>
        <h1 class="email-title" style="margin:8px 0 8px;font-size:30px;line-height:120%"><span aria-hidden="true">&#128218;</span> Library fun for {html.escape(child_name)}</h1>
        <p style="margin:0;font-size:16px;line-height:150%">{html.escape(intro)}</p>
      </td></tr>
      <tr><td class="email-content" style="padding:22px 0">{body}</td></tr>
      <tr><td class="email-footer" style="padding:18px 20px;background:#ffffff;border-radius:12px;color:#5f6368;font-size:13px;line-height:155%">
        {source_note}
        <strong style="color:#3c4043">Official branch calendars:</strong> {branch_links}
        <p style="margin:8px 0 0">Local age rules were applied to fetched event data. Confirm eligibility, registration, and current times in the official listing.</p>
        {calendar_note}
      </td></tr>
    </table>
  </td></tr></table>
</body>
</html>"""


def render_plain_text(
    events: Sequence[Event],
    *,
    child_name: str,
    birth_date: date,
    week_start: date,
    week_end: date,
    branches: Sequence[Branch],
    duration_minutes: int,
    source_errors: Sequence[str],
    source_warnings: Sequence[str],
    email_omitted_count: int = 0,
) -> str:
    lines = [
        f"LIBRARY FUN FOR {child_name.upper()}",
        _format_week_range(week_start, week_end),
        "",
        (
            f"Selected using local age rules for {child_name}; "
            f"age at the start of this week: {format_age(birth_date, week_start)}."
        ),
        "",
    ]
    if not events:
        lines.extend(
            [
                "No events matched the fetched data and current settings for this week.",
                "",
            ]
        )
    for event_date, day_items in groupby(events, key=lambda event: event.event_date):
        lines.extend([f"{event_date:%A, %B} {event_date.day}".upper(), ""])
        for event in day_items:
            chip_labels = [label for _kind, label in event_chip_specs(event)]
            age_categories = event_age_categories(event)
            directions = event_directions_url(event)
            location_line = event_location_summary(event)
            calendar_url = google_calendar_url(event, duration_minutes)
            if directions:
                location_line += f": {directions}"
            lines.extend(
                [
                    (
                        f"{format_event_time(event)} | "
                        f"{bounded_text(event.title, MAX_DISPLAY_TITLE_LENGTH)}"
                    ),
                    location_line,
                    *(
                        [
                            (
                                f"Library age listing: "
                                f"{(' ' + MIDDLE_DOT + ' ').join(age_categories)}"
                            )
                        ]
                        if age_categories
                        else []
                    ),
                    *([f"Highlights: {', '.join(chip_labels)}"] if chip_labels else []),
                    "",
                    event.description,
                    "",
                    *related_link_lines(event),
                ]
            )
            if event.description_links:
                lines.append("")
            lines.extend(
                [
                    *(
                        [f"Add to Google Calendar: {calendar_url}"]
                        if calendar_url
                        else []
                    ),
                    f"Event details: {event_details_url(event)}",
                    "",
                ]
            )
    if source_note := _source_note(source_errors, source_warnings):
        lines.append(source_note)
    if email_omitted_count:
        lines.extend(["", _email_omission_note(email_omitted_count)])
    lines.extend(["", "Official branch calendars:"])
    lines.extend(f"- {branch.name}: {branch.calendar_url}" for branch in branches)
    calendar_note = _calendar_placeholder_note(events, duration_minutes)
    if calendar_note:
        lines.extend(["", calendar_note])
    lines.extend(
        [
            "",
            (
                "Local age rules were applied to fetched event data. "
                "Confirm eligibility, registration, and current times in the official listing."
            ),
        ]
    )
    return "\n".join(lines)
