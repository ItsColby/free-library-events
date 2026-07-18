"""Deterministic Free Library event parsing, age matching, and email rendering."""

from __future__ import annotations

import calendar
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Sequence


TIMEZONE = "America/New_York"
FILTER_MODES = ("Strict", "Recommended", "Broad")
EN_DASH = "\N{EN DASH}"
MIDDLE_DOT = "\N{MIDDLE DOT}"


@dataclass(frozen=True, slots=True)
class Branch:
    """A supported Free Library branch."""

    code: str
    name: str
    address: str
    phone: str

    @property
    def rss_url(self) -> str:
        return f"https://libwww.freelibrary.org/rss/eventsrss.cfm?location={self.code}"

    @property
    def calendar_url(self) -> str:
        return f"https://libwww.freelibrary.org/calendar/?location_code={self.code}"


BRANCHES = {
    "SWK": Branch(
        code="SWK",
        name="Charles Santore Library",
        address="932 South 7th Street, Philadelphia, PA 19147",
        phone="215-686-1766",
    ),
    "IND": Branch(
        code="IND",
        name="Independence Library",
        address="18 South 7th Street, Philadelphia, PA 19106-2314",
        phone="215-685-1633",
    ),
}


@dataclass(frozen=True, slots=True)
class Event:
    """A normalized Free Library event."""

    title: str
    event_date: date
    start_time: time
    description: str
    link: str
    image_url: str
    branch: Branch

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.event_date, self.start_time)


@dataclass(frozen=True, slots=True)
class Fit:
    """Deterministic age-fit classification."""

    rank: str
    label: str
    reason: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"br", "p", "li", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


def next_week_start(reference_date: date) -> date:
    """Return the next Monday, treating Monday itself as this week's start."""

    return reference_date + timedelta(days=(7 - reference_date.weekday()) % 7)


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def age_on(birth_date: date, event_date: date) -> tuple[int, int, int]:
    """Return complete years, months, and days on an event date."""

    if event_date < birth_date:
        raise ValueError("Event date cannot precede birth date")
    months = (
        (event_date.year - birth_date.year) * 12 + event_date.month - birth_date.month
    )
    if add_months(birth_date, months) > event_date:
        months -= 1
    anchor = add_months(birth_date, months)
    return months // 12, months % 12, (event_date - anchor).days


def age_in_months(birth_date: date, event_date: date) -> float:
    years, months, days = age_on(birth_date, event_date)
    return years * 12 + months + days / 30.4375


def format_age(birth_date: date, event_date: date) -> str:
    years, months, days = age_on(birth_date, event_date)
    parts: list[str] = []
    if years:
        parts.append(f"{years} year" + ("s" if years != 1 else ""))
    if months:
        parts.append(f"{months} month" + ("s" if months != 1 else ""))
    if days or not parts:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    return ", ".join(parts)


def format_time(value: time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _repair_bare_numeric_entities(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        codepoint = int(match.group(1))
        return chr(codepoint) if 0 <= codepoint <= 0x10FFFF else match.group(0)

    return re.sub(r"(?<!&)#(\d{2,6});", replace, value)


def clean_description(raw_html: str, trailer: str) -> str:
    extractor = _HTMLTextExtractor()
    extractor.feed(_repair_bare_numeric_entities(raw_html))
    value = html.unescape(extractor.text()).strip()
    if trailer and value.endswith(trailer):
        value = value[: -len(trailer)].rstrip()
    return value


def clean_title(raw_title: str, branch: Branch) -> str:
    value = re.sub(r"^\d{2}/\d{2}/\d{2}:\s*", "", raw_title.strip())
    suffix = f" - {branch.name}"
    if value.endswith(suffix):
        value = value[: -len(suffix)]
    return value.replace("Storytime  Playgroup", "Storytime & Playgroup").strip()


def parse_feed(xml_content: bytes | str, branch: Branch) -> tuple[list[Event], int]:
    """Parse one official branch RSS feed."""

    root = ET.fromstring(xml_content)
    items = root.findall("./channel/item")
    events: list[Event] = []
    for item in items:
        start_date_text = (item.findtext("startdate") or "").strip()
        start_time_text = (item.findtext("starttime") or "").strip()
        if not start_date_text or not start_time_text:
            continue
        event_date = datetime.strptime(start_date_text, "%m/%d/%y").date()
        normalized_time = start_time_text.replace(".", "").strip()
        start_time = datetime.strptime(normalized_time, "%I:%M %p").time()
        trailer = f"{start_date_text}, {start_time_text} - {branch.name}"
        events.append(
            Event(
                title=clean_title(item.findtext("title") or "Library event", branch),
                event_date=event_date,
                start_time=start_time,
                description=clean_description(
                    item.findtext("description") or "", trailer
                ),
                link=(item.findtext("link") or item.findtext("guid") or "").strip(),
                image_url=(item.findtext("eventimage") or "")
                .strip()
                .replace("\\", "/"),
                branch=branch,
            )
        )
    return events, len(items)


AGE_RANGE_RE = re.compile(
    r"\bages?\s*(\d+)\s*(?:-|\u2013|to)\s*(\d+)\s*(months?|mos?|years?|yrs?)?\b",
    re.IGNORECASE,
)
AGE_AND_UNDER_RE = re.compile(
    r"\b(?:ages?\s*)?(\d+)\s*(months?|mos?|years?|yrs?)?\s+and under\b",
    re.IGNORECASE,
)
UNDER_AGE_RE = re.compile(
    r"\bunder\s+(\d+)\s*(months?|mos?|years?|yrs?)?\b", re.IGNORECASE
)


def _to_months(value: int, unit: str | None) -> float:
    return (
        float(value)
        if unit and unit.lower().startswith(("month", "mo"))
        else value * 12.0
    )


def _explicit_age_fit(text: str, child_months: float) -> Fit | None:
    match = AGE_RANGE_RE.search(text)
    if match:
        low = _to_months(int(match.group(1)), match.group(3))
        high = _to_months(int(match.group(2)), match.group(3))
        margin = (
            1
            if match.group(3) and match.group(3).lower().startswith(("month", "mo"))
            else 12
        )
        if low <= child_months < high + margin:
            return Fit(
                "best", "Great fit", "The published age range includes the child."
            )
        return Fit(
            "exclude",
            "Not age matched",
            "The published age range does not include the child.",
        )

    match = AGE_AND_UNDER_RE.search(text)
    if match:
        upper = _to_months(int(match.group(1)), match.group(2))
        margin = (
            1
            if match.group(2) and match.group(2).lower().startswith(("month", "mo"))
            else 12
        )
        if child_months < upper + margin:
            return Fit(
                "best", "Great fit", "The published maximum age includes the child."
            )
        return Fit(
            "exclude",
            "Not age matched",
            "The child is older than the published age range.",
        )

    match = UNDER_AGE_RE.search(text)
    if match:
        upper = _to_months(int(match.group(1)), match.group(2))
        if child_months < upper:
            return Fit(
                "best", "Great fit", "The published maximum age includes the child."
            )
        return Fit(
            "exclude",
            "Not age matched",
            "The child is older than the published age range.",
        )
    return None


def classify_event(event: Event, birth_date: date) -> Fit:
    """Classify an event using only deterministic published-text rules."""

    text = f"{event.title} {event.description}".lower()
    child_months = age_in_months(birth_date, event.event_date)
    explicit = _explicit_age_fit(text, child_months)
    if explicit is not None:
        return explicit

    baby_terms = ("baby", "babies", "infant", "lap sit", "lap-sit")
    toddler_terms = ("toddler", "toddlers", "twos")
    preschool_terms = ("preschool", "pre-school")
    school_age_terms = ("school age", "school-age")
    teen_terms = ("teen", "teens")
    adult_terms = ("adult", "adults")

    if child_months < 36 and any(term in text for term in baby_terms):
        return Fit(
            "best",
            "Great fit",
            "This event specifically welcomes babies or very young children.",
        )
    if 9 <= child_months < 48 and any(term in text for term in toddler_terms):
        return Fit(
            "best",
            "Great fit",
            "This event is intended for toddlers and their caregivers.",
        )
    if 30 <= child_months < 72 and any(term in text for term in preschool_terms):
        return Fit(
            "best", "Great fit", "This event is intended for preschool-age children."
        )
    if 60 <= child_months < 156 and any(term in text for term in school_age_terms):
        return Fit(
            "best", "Great fit", "This event is intended for school-age children."
        )
    if 144 <= child_months < 228 and any(term in text for term in teen_terms):
        return Fit("best", "Great fit", "This event is intended for teens.")

    if child_months < 36 and any(
        term in text
        for term in ("smallest kiddo", "youngest children", "littlest littles")
    ):
        return Fit(
            "good",
            "Age-friendly",
            "The description says even the youngest children can participate.",
        )

    if (
        child_months < 216
        and any(
            term in text
            for term in (
                "kids of all ages",
                "children of all ages",
                "all ages are welcome",
                "all ages welcome",
            )
        )
        and any(term in text for term in ("kid", "child", "family", "littlest"))
    ):
        return Fit("good", "Age-friendly", "The event welcomes children of all ages.")

    if child_months < 72 and ("range of ages" in text or "playgroup" in text):
        return Fit(
            "possible",
            "Likely a good fit",
            "The event offers a playgroup or activities for a range of ages.",
        )

    category_terms = (
        baby_terms
        + toddler_terms
        + preschool_terms
        + school_age_terms
        + teen_terms
        + adult_terms
    )
    if any(term in text for term in category_terms):
        return Fit(
            "exclude",
            "Not age matched",
            "The published audience does not match the child's current age.",
        )

    if child_months < 216 and any(
        term in text
        for term in (
            "kid",
            "child",
            "children",
            "family",
            "storytime",
            "craft",
            "sensory",
            "all ages",
        )
    ):
        return Fit(
            "broad",
            "Family option",
            "The event is published for children, families, or all ages.",
        )

    return Fit(
        "exclude",
        "Not age matched",
        "No matching child age or family audience was published.",
    )


def include_fit(fit: Fit, filter_mode: str) -> bool:
    if filter_mode == "Strict":
        return fit.rank == "best"
    if filter_mode == "Recommended":
        return fit.rank in {"best", "good", "possible"}
    if filter_mode == "Broad":
        return fit.rank in {"best", "good", "possible", "broad"}
    raise ValueError(f"Unsupported filter mode: {filter_mode}")


def matching_events(
    events: Sequence[Event],
    birth_date: date,
    filter_mode: str,
    start_date: date,
    end_date: date,
) -> list[tuple[Event, Fit]]:
    """Return deduplicated, sorted, included events in a date range."""

    deduplicated: dict[str, Event] = {}
    for event in events:
        if not start_date <= event.event_date <= end_date:
            continue
        key = event.link or (
            f"{event.branch.code}:{event.event_date}:{event.start_time}:{event.title}"
        )
        deduplicated[key] = event

    rank_order = {"best": 0, "good": 1, "possible": 2, "broad": 3}
    included: list[tuple[Event, Fit]] = []
    for event in deduplicated.values():
        fit = classify_event(event, birth_date)
        if include_fit(fit, filter_mode):
            included.append((event, fit))
    return sorted(
        included,
        key=lambda item: (
            item[0].starts_at,
            rank_order[item[1].rank],
            item[0].branch.name,
            item[0].title,
        ),
    )


def icon_for(event: Event) -> str:
    text = event.title.lower()
    if any(term in text for term in ("read", "story", "book")):
        return "\U0001f4da"
    if any(term in text for term in ("music", "sing", "karaoke")):
        return "\U0001f3b5"
    if any(term in text for term in ("craft", "origami", "art")):
        return "\U0001f3a8"
    if any(term in text for term in ("playgroup", "play group", "playtime")):
        return "\U0001f9f8"
    return "\N{SPARKLES}"


def google_calendar_url(event: Event, duration_minutes: int) -> str:
    end = event.starts_at + timedelta(minutes=duration_minutes)
    details = (
        f"{event.description}\n\n"
        f"Official event details: {event.link}\n\n"
        "The library did not publish an end time. "
        f"The {duration_minutes}-minute duration is a calendar placeholder."
    )
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
        {
            "action": "TEMPLATE",
            "text": event.title,
            "dates": f"{event.starts_at:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}",
            "ctz": TIMEZONE,
            "location": f"{event.branch.name}, {event.branch.address}",
            "details": details,
        }
    )


def directions_url(branch: Branch) -> str:
    return "https://www.google.com/maps/search/?" + urllib.parse.urlencode(
        {"api": "1", "query": f"{branch.name}, {branch.address}"}
    )


def registration_text(description: str) -> str:
    text = description.lower()
    if "no registration" in text or "registration is not required" in text:
        return "No registration required"
    if "registration required" in text or "register " in text or "register at" in text:
        return f"Registration may be required {EN_DASH} check the event page"
    return "No registration information listed"


def cost_text(description: str) -> str:
    return (
        "Free"
        if re.search(r"\bfree\b|\bno cost\b", description.lower())
        else "No cost information listed"
    )


def _button(label: str, url: str, primary: bool = False) -> str:
    background = "#1967d2" if primary else "#ffffff"
    color = "#ffffff" if primary else "#1967d2"
    return (
        f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;'
        f"margin:6px 8px 0 0;padding:11px 15px;border:1px solid #1967d2;"
        f"border-radius:8px;background:{background};color:{color};font-weight:700;"
        f'text-decoration:none;font-size:14px">{html.escape(label)}</a>'
    )


def _format_week_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start:%B} {start.day}{EN_DASH}{end.day}, {end.year}"
    return f"{start:%B} {start.day}{EN_DASH}{end:%B} {end.day}, {end.year}"


def _subject_week_range(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start:%b} {start.day}{EN_DASH}{end.day}"
    return f"{start:%b} {start.day}{EN_DASH}{end:%b} {end.day}"


def _render_html(
    events_with_fits: Sequence[tuple[Event, Fit]],
    *,
    child_name: str,
    birth_date: date,
    week_start: date,
    week_end: date,
    branches: Sequence[Branch],
    duration_minutes: int,
    scanned_count: int,
    source_counts: dict[str, int],
    source_errors: Sequence[str],
    generated_on: date,
) -> str:
    cards: list[str] = []
    for event, fit in events_with_fits:
        image = ""
        if event.image_url:
            image = (
                f'<img src="{html.escape(event.image_url, quote=True)}" '
                f'alt="{html.escape(event.title, quote=True)}" '
                'style="display:block;width:100%;height:auto;max-height:320px;object-fit:cover">'
            )
        cards.append(
            f"""
            <div style="margin:0 0 18px;background:#ffffff;border:1px solid #e3e7ee;border-radius:14px;overflow:hidden">
              {image}
              <div style="padding:18px 20px">
                <div style="font-size:13px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#5f6368">{event.event_date:%A, %B} {event.event_date.day}</div>
                <div style="margin-top:8px"><span style="display:inline-block;padding:5px 9px;border-radius:999px;background:#e6f4ea;color:#137333;font-size:12px;font-weight:800">{html.escape(fit.label)}</span></div>
                <h2 style="margin:10px 0 6px;color:#202124;font-size:22px;line-height:1.25">{icon_for(event)} {html.escape(event.title)}</h2>
                <div style="font-size:16px;font-weight:700;color:#202124">{format_time(event.start_time)} {MIDDLE_DOT} {html.escape(event.branch.name)}</div>
                <div style="margin-top:5px;color:#5f6368;font-size:14px;line-height:1.5">{html.escape(event.branch.address)}<br>{html.escape(event.branch.phone)}</div>
                <div style="margin-top:14px;padding:12px 14px;background:#f8fafd;border-radius:10px;color:#3c4043;font-size:14px;line-height:1.5"><strong>Why it fits:</strong> {html.escape(fit.reason)}<br><strong>{html.escape(child_name)} will be:</strong> {html.escape(format_age(birth_date, event.event_date))} old</div>
                <p style="margin:16px 0 12px;color:#3c4043;font-size:15px;line-height:1.65;white-space:pre-line">{html.escape(event.description)}</p>
                <table role="presentation" style="width:100%;border-collapse:collapse;color:#3c4043;font-size:14px;line-height:1.5">
                  <tr><td style="padding:4px 10px 4px 0;font-weight:700;vertical-align:top">Registration</td><td style="padding:4px 0">{html.escape(registration_text(event.description))}</td></tr>
                  <tr><td style="padding:4px 10px 4px 0;font-weight:700;vertical-align:top">Cost</td><td style="padding:4px 0">{html.escape(cost_text(event.description))}</td></tr>
                  <tr><td style="padding:4px 10px 4px 0;font-weight:700;vertical-align:top">End time</td><td style="padding:4px 0">Not listed by the library</td></tr>
                </table>
                <div style="margin-top:12px">
                  {_button("Add to Google Calendar", google_calendar_url(event, duration_minutes), primary=True)}
                  {_button("Event details", event.link)}
                  {_button("Directions", directions_url(event.branch))}
                </div>
              </div>
            </div>
            """
        )

    if cards:
        body = "".join(cards)
        intro = (
            f"Here are {len(cards)} activities at your selected libraries that fit "
            f"{child_name}'s current age."
        )
    else:
        intro = f"No clearly age-matched activities were published for {child_name} this week."
        body = (
            '<div style="padding:20px;background:#ffffff;border:1px solid #e3e7ee;'
            'border-radius:14px;color:#3c4043">Nothing suitable was found in the published feeds. '
            "The full branch calendars are linked below.</div>"
        )

    branch_links = f" {MIDDLE_DOT} ".join(
        f'<a href="{html.escape(branch.calendar_url, quote=True)}" style="color:#1967d2">{html.escape(branch.name.replace(" Library", ""))}</a>'
        for branch in branches
    )
    source_note = ""
    ten_item_branches = [name for name, count in source_counts.items() if count >= 10]
    if ten_item_branches:
        source_note += (
            '<p style="margin:8px 0 0">The published feed returned 10 items for '
            + html.escape(" and ".join(ten_item_branches))
            + ", so use the full-calendar links to double-check for additional events.</p>"
        )
    if source_errors:
        source_note += (
            '<p style="margin:8px 0 0;color:#b3261e">We could not load: '
            + html.escape("; ".join(source_errors))
            + ".</p>"
        )

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Library fun for {html.escape(child_name)}</title></head>
<body style="margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#202124">
  <div style="display:none;max-height:0;overflow:hidden">Age-matched library activities for {_format_week_range(week_start, week_end)}.</div>
  <table role="presentation" style="width:100%;border-collapse:collapse;background:#f3f6fb"><tr><td align="center" style="padding:20px 10px">
    <table role="presentation" style="width:100%;max-width:680px;border-collapse:collapse">
      <tr><td style="padding:24px 24px 20px;background:#174ea6;border-radius:16px 16px 0 0;color:#ffffff">
        <div style="font-size:13px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;opacity:.85">{_format_week_range(week_start, week_end)}</div>
        <h1 style="margin:8px 0 8px;font-size:30px;line-height:1.2">&#128218; Library fun for {html.escape(child_name)}</h1>
        <p style="margin:0;font-size:16px;line-height:1.5">{html.escape(intro)}</p>
        <p style="margin:10px 0 0;font-size:14px;opacity:.9">{html.escape(child_name)} is {html.escape(format_age(birth_date, week_start))} to {html.escape(format_age(birth_date, week_end))} old this week.</p>
      </td></tr>
      <tr><td style="padding:22px 0">{body}</td></tr>
      <tr><td style="padding:18px 20px;background:#ffffff;border-radius:12px;color:#5f6368;font-size:13px;line-height:1.55">
        <strong style="color:#3c4043">See every published event:</strong> {branch_links}
        <p style="margin:8px 0 0">Library schedules can change, so check the official event page before leaving. Calendar buttons use a {duration_minutes}-minute placeholder when the library does not publish an end time.</p>
        {source_note}
        <p style="margin:8px 0 0">Prepared automatically by Home Assistant on {generated_on:%B} {generated_on.day}, {generated_on.year}. {scanned_count} events were checked.</p>
      </td></tr>
    </table>
  </td></tr></table>
</body>
</html>"""


def _render_plain_text(
    events_with_fits: Sequence[tuple[Event, Fit]],
    *,
    child_name: str,
    birth_date: date,
    week_start: date,
    week_end: date,
    branches: Sequence[Branch],
    duration_minutes: int,
) -> str:
    lines = [
        f"LIBRARY FUN FOR {child_name.upper()}",
        _format_week_range(week_start, week_end),
        "",
        f"{child_name} is {format_age(birth_date, week_start)} to {format_age(birth_date, week_end)} old this week.",
        "",
    ]
    if not events_with_fits:
        lines.extend(["No clearly age-matched events were found.", ""])
    for event, fit in events_with_fits:
        lines.extend(
            [
                f"{event.event_date:%A, %B} {event.event_date.day} {EN_DASH} {format_time(event.start_time)}",
                event.title,
                f"{fit.label}: {fit.reason}",
                f"{child_name} will be {format_age(birth_date, event.event_date)} old.",
                f"{event.branch.name} {EN_DASH} {event.branch.address} {EN_DASH} {event.branch.phone}",
                "",
                event.description,
                "",
                f"Registration: {registration_text(event.description)}",
                f"Cost: {cost_text(event.description)}",
                "End time: Not listed by the library",
                f"Add to Google Calendar: {google_calendar_url(event, duration_minutes)}",
                f"Event details: {event.link}",
                f"Directions: {directions_url(event.branch)}",
                "",
            ]
        )
    lines.append("Full branch calendars:")
    lines.extend(f"- {branch.name}: {branch.calendar_url}" for branch in branches)
    lines.extend(
        [
            "",
            "Library schedules can change, so check the official event page before leaving.",
        ]
    )
    return "\n".join(lines)


def build_digest(
    *,
    child_name: str,
    birth_date: date,
    filter_mode: str,
    duration_minutes: int,
    selected_branches: Sequence[Branch],
    reference_date: date,
    events: Sequence[Event],
    source_counts: dict[str, int],
    source_errors: Sequence[str] = (),
) -> dict[str, object]:
    """Build the complete JSON-serializable email response."""

    child_name = child_name.strip()
    if not child_name:
        raise ValueError("Child name is required")
    if not selected_branches:
        raise ValueError("At least one library branch must be enabled")
    if filter_mode not in FILTER_MODES:
        raise ValueError(f"Filter mode must be one of: {', '.join(FILTER_MODES)}")
    if not 15 <= duration_minutes <= 240:
        raise ValueError(
            "Calendar placeholder duration must be between 15 and 240 minutes"
        )

    week_start = next_week_start(reference_date)
    week_end = week_start + timedelta(days=6)
    weekly_events = {
        event.link
        or f"{event.branch.code}:{event.event_date}:{event.start_time}:{event.title}": event
        for event in events
        if week_start <= event.event_date <= week_end
    }
    included = matching_events(
        list(weekly_events.values()),
        birth_date,
        filter_mode,
        week_start,
        week_end,
    )
    subject = (
        f"{len(included)} library activit{'y' if len(included) == 1 else 'ies'} "
        f"for {child_name} this week \U0001f4da | {_subject_week_range(week_start, week_end)}"
    )
    return {
        "subject": subject,
        "message": _render_plain_text(
            included,
            child_name=child_name,
            birth_date=birth_date,
            week_start=week_start,
            week_end=week_end,
            branches=selected_branches,
            duration_minutes=duration_minutes,
        ),
        "html": _render_html(
            included,
            child_name=child_name,
            birth_date=birth_date,
            week_start=week_start,
            week_end=week_end,
            branches=selected_branches,
            duration_minutes=duration_minutes,
            scanned_count=len(weekly_events),
            source_counts=source_counts,
            source_errors=source_errors,
            generated_on=reference_date,
        ),
        "metadata": {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "filter_mode": filter_mode,
            "scanned_count": len(weekly_events),
            "included_count": len(included),
            "omitted_count": len(weekly_events) - len(included),
            "included_event_ids": [
                event.link.rsplit("/", 1)[-1] for event, _ in included
            ],
            "source_counts": dict(source_counts),
            "source_errors": list(source_errors),
        },
    }
