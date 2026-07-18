"""Deterministic Free Library event parsing, age matching, and email rendering."""

from __future__ import annotations

import calendar
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from itertools import groupby
from typing import Literal, Sequence


TIMEZONE = "America/New_York"
FILTER_MODES = ("Strict", "Recommended", "Broad")
EN_DASH = "\N{EN DASH}"
MIDDLE_DOT = "\N{MIDDLE DOT}"

# Stable source taxonomy with intentionally overlapping local windows. The
# library publishes these category names but does not publish numeric bounds.
# Household age/category choices are derived at refresh time, never stored here.
AGE_CATEGORY_WINDOWS: tuple[tuple[str, float, float], ...] = (
    ("Baby", 0, 36),
    ("Toddler", 9, 48),
    ("Preschool", 30, 72),
    ("School Age", 60, 156),
    ("Young Adult", 144, 228),
    ("Adult", 216, float("inf")),
    ("Senior", 720, float("inf")),
)
AGE_CATEGORY_ORDER = {
    category: index
    for index, (category, _minimum, _maximum) in enumerate(AGE_CATEGORY_WINDOWS)
}


@dataclass(frozen=True, slots=True)
class Branch:
    """A supported Free Library branch."""

    code: str
    name: str
    address: str

    @property
    def rss_url(self) -> str:
        return f"https://libwww.freelibrary.org/rss/eventsrss.cfm?location={self.code}"

    def rss_url_for_age(self, age_category: str) -> str:
        """Return the official custom feed for this branch and age category."""

        if age_category not in AGE_CATEGORY_ORDER:
            raise ValueError(f"Unsupported official age category: {age_category}")
        return f"{self.rss_url}&{urllib.parse.urlencode({'age': age_category})}"

    @property
    def calendar_url(self) -> str:
        return f"https://libwww.freelibrary.org/calendar/?location_code={self.code}"


BRANCHES = {
    "SWK": Branch(
        code="SWK",
        name="Charles Santore Library",
        address="932 South 7th Street, Philadelphia, PA 19147",
    ),
    "IND": Branch(
        code="IND",
        name="Independence Library",
        address="18 South 7th Street, Philadelphia, PA 19106-2314",
    ),
    "CEN": Branch(
        code="CEN",
        name="Parkway Central Library",
        address="1901 Vine Street, Philadelphia, PA 19103-1189",
    ),
    "PCI": Branch(
        code="PCI",
        name="Philadelphia City Institute",
        address="1905 Locust Street, Philadelphia, PA 19103-5730",
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
    age_categories: tuple[str, ...] = ()
    end_at: datetime | None = None

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.event_date, self.start_time)


type FitRank = Literal["best", "good", "possible", "broad", "exclude"]


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


def age_categories_for_window(
    birth_date: date,
    start_date: date,
    end_date: date,
) -> tuple[str, ...]:
    """Return official age filters that overlap the child's age in a date range."""

    if end_date < start_date:
        raise ValueError("Age-category window end cannot precede its start")
    start_months = age_in_months(birth_date, start_date)
    end_months = age_in_months(birth_date, end_date)
    return tuple(
        category
        for category, minimum, maximum in AGE_CATEGORY_WINDOWS
        if end_months >= minimum and start_months < maximum
    )


def format_age(birth_date: date, event_date: date) -> str:
    """Return a conversational age without day-level precision."""

    years, months, _ = age_on(birth_date, event_date)
    completed_months = years * 12 + months
    elapsed_days = (event_date - birth_date).days
    if completed_months < 2:
        completed_weeks = elapsed_days // 7
        if completed_weeks == 0:
            return "under 1 week"
        return f"{completed_weeks} week" + ("s" if completed_weeks != 1 else "")
    if completed_months < 24:
        return f"{completed_months} month" + ("s" if completed_months != 1 else "")
    if years < 5 and 5 <= months <= 7:
        return f"{years}½ years"
    return f"{years} year" + ("s" if years != 1 else "")


def format_time(value: time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def format_event_time(event: Event) -> str:
    """Return a start time and any confident official end time."""

    if event.end_at:
        return f"{format_time(event.start_time)} {EN_DASH} {format_time(event.end_at.time())}"
    return format_time(event.start_time)


TIME_RANGE_RE = re.compile(
    r"\b(?P<start_hour>\d{1,2})(?::(?P<start_minute>\d{2}))?\s*"
    r"(?P<start_meridiem>a\.?m\.?|p\.?m\.?)?\s*"
    r"(?:-|\u2013|\u2014|to)\s*"
    r"(?P<end_hour>\d{1,2})(?::(?P<end_minute>\d{2}))?\s*"
    r"(?P<end_meridiem>a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)


def _clock_time(hour: str, minute: str | None, meridiem: str) -> time | None:
    value = int(hour)
    if not 1 <= value <= 12:
        return None
    minute_value = int(minute or 0)
    if not 0 <= minute_value <= 59:
        return None
    normalized_meridiem = meridiem.lower().replace(".", "")
    if normalized_meridiem == "pm" and value != 12:
        value += 12
    elif normalized_meridiem == "am" and value == 12:
        value = 0
    return time(value, minute_value)


def explicit_end_at(
    event_date: date,
    start_time: time,
    description: str,
) -> datetime | None:
    """Return an end time only for an explicit range matching the event start."""

    for match in TIME_RANGE_RE.finditer(description):
        end_meridiem = match.group("end_meridiem")
        source_start = _clock_time(
            match.group("start_hour"),
            match.group("start_minute"),
            match.group("start_meridiem") or end_meridiem,
        )
        source_end = _clock_time(
            match.group("end_hour"),
            match.group("end_minute"),
            end_meridiem,
        )
        if source_start != start_time or source_end is None:
            continue
        start_at = datetime.combine(event_date, start_time)
        end_at = datetime.combine(event_date, source_end)
        if timedelta(minutes=15) <= end_at - start_at <= timedelta(hours=8):
            return end_at
    return None


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
    value = re.sub(r"\bBaby\s{2,}Toddler\b", "Baby & Toddler", value)
    return value.replace("Storytime  Playgroup", "Storytime & Playgroup").strip()


def parse_feed(
    xml_content: bytes | str,
    branch: Branch,
    age_category: str | None = None,
) -> tuple[list[Event], int]:
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
        description = clean_description(item.findtext("description") or "", trailer)
        events.append(
            Event(
                title=clean_title(item.findtext("title") or "Library event", branch),
                event_date=event_date,
                start_time=start_time,
                description=description,
                link=(item.findtext("link") or item.findtext("guid") or "").strip(),
                image_url=(item.findtext("eventimage") or "")
                .strip()
                .replace("\\", "/"),
                branch=branch,
                age_categories=(age_category,) if age_category else (),
                end_at=explicit_end_at(event_date, start_time, description),
            )
        )
    return events, len(items)


def merge_events(events: Sequence[Event]) -> list[Event]:
    """Deduplicate events while preserving every official age classification."""

    merged: dict[str, Event] = {}
    for event in events:
        key = event.link or (
            f"{event.branch.code}:{event.event_date}:{event.start_time}:{event.title}"
        )
        if existing := merged.get(key):
            age_categories = tuple(
                sorted(
                    {*existing.age_categories, *event.age_categories},
                    key=lambda category: AGE_CATEGORY_ORDER.get(category, 999),
                )
            )
            merged[key] = replace(existing, age_categories=age_categories)
        else:
            merged[key] = event
    return list(merged.values())


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


def _is_broad_years_only_upper_limit(
    value: int, unit: str | None, child_months: float
) -> bool:
    """Detect upper limits too broad to establish an early-childhood fit."""

    is_years = unit is None or unit.lower().startswith(("year", "yr"))
    return child_months < 36 and is_years and value >= 6


def _explicit_age_fit(text: str, child_months: float) -> FitRank | None:
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
            return "best"
        return "exclude"

    match = AGE_AND_UNDER_RE.search(text)
    if match:
        upper_value = int(match.group(1))
        upper_unit = match.group(2)
        upper = _to_months(upper_value, upper_unit)
        margin = (
            1 if upper_unit and upper_unit.lower().startswith(("month", "mo")) else 12
        )
        if child_months < upper + margin:
            if _is_broad_years_only_upper_limit(upper_value, upper_unit, child_months):
                return "broad"
            return "best"
        return "exclude"

    match = UNDER_AGE_RE.search(text)
    if match:
        upper_value = int(match.group(1))
        upper_unit = match.group(2)
        upper = _to_months(upper_value, upper_unit)
        if child_months < upper:
            if _is_broad_years_only_upper_limit(upper_value, upper_unit, child_months):
                return "broad"
            return "best"
        return "exclude"
    return None


def classify_event(event: Event, birth_date: date) -> FitRank:
    """Classify an event using only deterministic published-text rules."""

    text = f"{event.title} {event.description}".lower()
    child_months = age_in_months(birth_date, event.event_date)
    explicit = _explicit_age_fit(text, child_months)
    if explicit is not None:
        return explicit

    if event.age_categories:
        for category, minimum, maximum in AGE_CATEGORY_WINDOWS:
            if category in event.age_categories and minimum <= child_months < maximum:
                return "best"
        return "exclude"

    baby_terms = ("baby", "babies", "infant", "lap sit", "lap-sit")
    toddler_terms = ("toddler", "toddlers", "twos")
    preschool_terms = ("preschool", "pre-school")
    school_age_terms = ("school age", "school-age")
    teen_terms = ("teen", "teens")
    adult_terms = ("adult", "adults")

    if child_months < 36 and any(term in text for term in baby_terms):
        return "best"
    if 9 <= child_months < 48 and any(term in text for term in toddler_terms):
        return "best"
    if 30 <= child_months < 72 and any(term in text for term in preschool_terms):
        return "best"
    if 60 <= child_months < 156 and any(term in text for term in school_age_terms):
        return "best"
    if 144 <= child_months < 228 and any(term in text for term in teen_terms):
        return "best"

    if child_months < 36 and any(
        term in text
        for term in ("smallest kiddo", "youngest children", "littlest littles")
    ):
        return "good"

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
        return "good"

    if child_months < 72 and ("range of ages" in text or "playgroup" in text):
        return "possible"

    category_terms = (
        baby_terms
        + toddler_terms
        + preschool_terms
        + school_age_terms
        + teen_terms
        + adult_terms
    )
    if any(term in text for term in category_terms):
        return "exclude"

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
        return "broad"

    return "exclude"


def include_fit(fit: FitRank, filter_mode: str) -> bool:
    if filter_mode == "Strict":
        return fit == "best"
    if filter_mode == "Recommended":
        return fit in {"best", "good", "possible"}
    if filter_mode == "Broad":
        return fit in {"best", "good", "possible", "broad"}
    raise ValueError(f"Unsupported filter mode: {filter_mode}")


def matching_events(
    events: Sequence[Event],
    birth_date: date,
    filter_mode: str,
    start_date: date,
    end_date: date,
) -> list[Event]:
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
    included: list[tuple[Event, FitRank]] = []
    for event in deduplicated.values():
        fit = classify_event(event, birth_date)
        if include_fit(fit, filter_mode):
            included.append((event, fit))
    return [
        event
        for event, _ in sorted(
            included,
            key=lambda item: (
                item[0].starts_at,
                rank_order[item[1]],
                item[0].branch.name,
                item[0].title,
            ),
        )
    ]


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
    end = event.end_at or event.starts_at + timedelta(minutes=duration_minutes)
    details = f"{event.description}\n\nOfficial event details: {event.link}"
    if event.end_at is None:
        details += (
            "\n\nThe library did not publish an end time. "
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


def _source_notes(
    source_errors: Sequence[str],
    source_warnings: Sequence[str],
) -> list[tuple[str, bool]]:
    """Return consistent source-coverage disclosures for both email bodies."""

    notes: list[tuple[str, bool]] = []
    if source_warnings:
        notes.append(
            ("Source coverage is unresolved: " + "; ".join(source_warnings) + ".", True)
        )
    if source_errors:
        notes.append(("We could not load: " + "; ".join(source_errors) + ".", True))
    return notes


def _render_event_card(
    event: Event,
    *,
    duration_minutes: int,
) -> str:
    event_url = html.escape(event.link, quote=True)
    image = ""
    if event.image_url:
        image = (
            '<div style="padding:0;background:#f8fafd;text-align:center">'
            f'<a href="{event_url}" style="display:block;text-decoration:none">'
            f'<img src="{html.escape(event.image_url, quote=True)}" '
            f'alt="{html.escape(event.title, quote=True)}" '
            'style="display:block;width:auto;max-width:100%;height:auto;max-height:560px;'
            'margin:0 auto;object-fit:contain"></a></div>'
        )
    map_url = html.escape(directions_url(event.branch), quote=True)
    return f"""
    <div style="margin:0 0 12px;background:#ffffff;border:1px solid #e3e7ee;border-radius:14px;overflow:hidden">
      {image}
      <div style="padding:18px 20px">
        <h3 style="margin:0 0 6px;color:#202124;font-size:22px;line-height:1.25">{icon_for(event)} <a href="{event_url}" style="color:#174ea6;text-decoration:underline;text-decoration-color:#a8c7fa;text-underline-offset:3px">{html.escape(event.title)}</a></h3>
        <div style="font-size:16px;font-weight:700;color:#202124">{format_event_time(event)} {MIDDLE_DOT} <a href="{map_url}" style="color:#202124;text-decoration:underline;text-decoration-color:#c4c7c5;text-underline-offset:3px">{html.escape(event.branch.name)}</a></div>
        <p style="margin:16px 0 12px;color:#3c4043;font-size:15px;line-height:1.65;white-space:pre-line">{html.escape(event.description)}</p>
        <div style="margin-top:12px">
          {_button("Add to Google Calendar", google_calendar_url(event, duration_minutes), primary=True)}
        </div>
      </div>
    </div>
    """


def _render_html(
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
) -> str:
    day_sections: list[str] = []
    for event_date, day_items in groupby(events, key=lambda event: event.event_date):
        day_cards = "".join(
            _render_event_card(
                event,
                duration_minutes=duration_minutes,
            )
            for event in day_items
        )
        day_sections.append(
            f"""
            <div style="margin:0 0 24px">
              <h2 style="margin:0 0 10px;padding:0 4px;color:#174ea6;font-size:20px;font-weight:800;line-height:1.3">{event_date:%A, %B} {event_date.day}</h2>
              {day_cards}
            </div>
            """
        )

    if day_sections:
        body = "".join(day_sections)
        activity_noun = "activity" if len(events) == 1 else "activities"
        intro_verb = "is" if len(events) == 1 else "are"
        intro = (
            f"Here {intro_verb} {len(events)} {activity_noun} from your libraries for "
            f"{child_name}, who is {format_age(birth_date, week_start)} old."
        )
    else:
        intro = (
            f"No clearly age-matched activities were published for {child_name}, "
            f"who is {format_age(birth_date, week_start)} old, this week."
        )
        body = (
            '<div style="padding:20px;background:#ffffff;border:1px solid #e3e7ee;'
            'border-radius:14px;color:#3c4043">Nothing suitable was found in the published feeds. '
            "The full branch calendars are linked below.</div>"
        )

    branch_links = f" {MIDDLE_DOT} ".join(
        f'<a href="{html.escape(branch.calendar_url, quote=True)}" style="color:#1967d2">{html.escape(branch.name.replace(" Library", ""))}</a>'
        for branch in branches
    )
    source_note_parts: list[str] = []
    for note, is_error in _source_notes(source_errors, source_warnings):
        color = ";color:#b3261e" if is_error else ""
        source_note_parts.append(
            f'<p style="margin:8px 0 0{color}">{html.escape(note)}</p>'
        )
    source_note = "".join(source_note_parts)

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
      </td></tr>
      <tr><td style="padding:22px 0">{body}</td></tr>
      <tr><td style="padding:18px 20px;background:#ffffff;border-radius:12px;color:#5f6368;font-size:13px;line-height:1.55">
        <strong style="color:#3c4043">See every published event:</strong> {branch_links}
        <p style="margin:8px 0 0">Library schedules can change, so check the official event page before leaving.</p>
        {source_note}
      </td></tr>
    </table>
  </td></tr></table>
</body>
</html>"""


def _render_plain_text(
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
) -> str:
    lines = [
        f"LIBRARY FUN FOR {child_name.upper()}",
        _format_week_range(week_start, week_end),
        "",
        f"Selected for {child_name}, who is {format_age(birth_date, week_start)} old.",
        "",
    ]
    if not events:
        lines.extend(["No clearly age-matched events were found.", ""])
    for event_date, day_items in groupby(events, key=lambda event: event.event_date):
        lines.extend([f"{event_date:%A, %B} {event_date.day}".upper(), ""])
        for event in day_items:
            lines.extend(
                [
                    f"{format_event_time(event)} | {event.title}",
                    f"{event.branch.name}: {directions_url(event.branch)}",
                    "",
                    event.description,
                    "",
                ]
            )
            lines.extend(
                [
                    f"Add to Google Calendar: {google_calendar_url(event, duration_minutes)}",
                    f"Event details: {event.link}",
                    "",
                ]
            )
    lines.append("Full branch calendars:")
    lines.extend(f"- {branch.name}: {branch.calendar_url}" for branch in branches)
    plain_source_notes = [
        note for note, _ in _source_notes(source_errors, source_warnings)
    ]
    if plain_source_notes:
        lines.extend(["", *plain_source_notes])
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
    source_warnings: Sequence[str] = (),
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
            source_errors=source_errors,
            source_warnings=source_warnings,
        ),
        "html": _render_html(
            included,
            child_name=child_name,
            birth_date=birth_date,
            week_start=week_start,
            week_end=week_end,
            branches=selected_branches,
            duration_minutes=duration_minutes,
            source_errors=source_errors,
            source_warnings=source_warnings,
        ),
        "metadata": {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "filter_mode": filter_mode,
            "scanned_count": len(weekly_events),
            "included_count": len(included),
            "omitted_count": len(weekly_events) - len(included),
            "included_event_ids": [event.link.rsplit("/", 1)[-1] for event in included],
            "source_counts": dict(source_counts),
            "source_errors": list(source_errors),
            "source_warnings": list(source_warnings),
        },
    }
