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
from typing import Literal, Mapping, Sequence


TIMEZONE = "America/New_York"
FILTER_MODES = ("Strict", "Recommended", "Broad")
EN_DASH = "\N{EN DASH}"
MIDDLE_DOT = "\N{MIDDLE DOT}"
MAX_CHILD_NAME_LENGTH = 80
MAX_DESCRIPTION_LINKS = 50
MAX_EVENT_DESCRIPTION_LENGTH = 50_000
MAX_EVENT_TITLE_LENGTH = 500
MAX_PARSED_RSS_ITEMS = 100
MAX_URL_LENGTH = 2_048
MAX_DISPLAY_TITLE_LENGTH = 180
MAX_CARD_DESCRIPTION_CHARS = 1_800
MAX_CALENDAR_DETAILS_CHARS = 1_200
MAX_CALENDAR_URL_LENGTH = 4_096
MAX_DIGEST_HTML_BYTES = 80_000
MAX_EMAIL_EVENTS = 100
MAX_EVENT_CHIPS = 5
TRUSTED_IMAGE_HOSTS = frozenset({"libwww.freelibrary.org", "www.freelibrary.org"})

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
MINOR_SOURCE_CATEGORIES = (
    "Baby",
    "Toddler",
    "Preschool",
    "School Age",
    "Young Adult",
)
ADULT_START_MONTHS = 18 * 12


@dataclass(frozen=True, slots=True)
class Branch:
    """A supported Free Library branch."""

    code: str
    name: str
    address: str
    latitude: float
    longitude: float

    @property
    def rss_url(self) -> str:
        return f"https://libwww.freelibrary.org/rss/eventsrss.cfm?location={self.code}"

    def rss_url_for_age(self, age_category: str) -> str:
        """Return the official custom feed for this branch and age category."""

        if age_category not in AGE_CATEGORY_ORDER:
            raise ValueError(f"Unsupported official age category: {age_category}")
        return f"{self.rss_url}&{urllib.parse.urlencode({'age': age_category})}"

    def rss_url_for_age_and_type(self, age_category: str, event_type: str) -> str:
        """Return an official age feed narrowed by one publisher event type."""

        return (
            f"{self.rss_url_for_age(age_category)}&"
            f"{urllib.parse.urlencode({'type': event_type})}"
        )

    @property
    def calendar_url(self) -> str:
        return f"https://libwww.freelibrary.org/calendar/?location_code={self.code}"


BRANCHES = {
    "SWK": Branch(
        code="SWK",
        name="Charles Santore Library",
        address="932 South 7th Street, Philadelphia, PA 19147",
        latitude=39.937044,
        longitude=-75.155274,
    ),
    "IND": Branch(
        code="IND",
        name="Independence Library",
        address="18 South 7th Street, Philadelphia, PA 19106-2314",
        latitude=39.9504517,
        longitude=-75.1524099,
    ),
    "CEN": Branch(
        code="CEN",
        name="Parkway Central Library",
        address="1901 Vine Street, Philadelphia, PA 19103-1189",
        latitude=39.959302,
        longitude=-75.171102,
    ),
    "PCI": Branch(
        code="PCI",
        name="Philadelphia City Institute",
        address="1905 Locust Street, Philadelphia, PA 19103-5730",
        latitude=39.949453,
        longitude=-75.173354,
    ),
}


@dataclass(frozen=True, slots=True)
class DescriptionLink:
    """A safe link explicitly embedded in official RSS description HTML."""

    label: str
    url: str
    occurrence: int = 0


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
    description_links: tuple[DescriptionLink, ...] = ()
    description_html: str = ""
    venue: str = ""
    room: str = ""
    modality: Literal["in_person", "online", "hybrid"] = "in_person"
    image_layout: Literal["side", "hero"] = "side"
    description_truncated: bool = False

    @property
    def starts_at(self) -> datetime:
        return datetime.combine(self.event_date, self.start_time)


type FitRank = Literal["best", "good", "possible", "broad", "exclude"]


def _safe_http_url(value: str, base_url: str = "") -> str:
    try:
        value = value.strip()
        if len(value) > MAX_URL_LENGTH:
            return ""
        url = urllib.parse.urljoin(base_url, value)
        if len(url) > MAX_URL_LENGTH:
            return ""
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        return ""
    return (
        url
        if parsed.scheme in {"http", "https"}
        and parsed.netloc
        and hostname
        and parsed.username is None
        and parsed.password is None
        else ""
    )


class _HTMLTextExtractor(HTMLParser):
    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self.links: list[DescriptionLink] = []
        self._link_url = ""
        self._link_parts: list[str] | None = None
        self._suppressed_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._suppressed_depth:
            self._suppressed_depth += 1
            return
        if tag in {"script", "style"}:
            self._suppressed_depth = 1
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag in {"p", "li", "div"}:
            self.parts.append("\n\n")
        if tag == "a":
            values = {key.lower(): value or "" for key, value in attrs}
            self._link_url = _safe_http_url(values.get("href", ""), self.base_url)
            self._link_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._suppressed_depth:
            self._suppressed_depth -= 1
            return
        if tag in {"p", "li", "div"}:
            self.parts.append("\n\n")
        if tag == "a" and self._link_parts is not None:
            label = " ".join(" ".join(self._link_parts).split())
            if self._link_url and label:
                occurrence = max(self.text().count(label) - 1, 0)
                link = DescriptionLink(label, self._link_url, occurrence)
                if link not in self.links:
                    self.links.append(link)
            self._link_url = ""
            self._link_parts = None

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        self.parts.append(data)
        if self._link_parts is not None:
            self._link_parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        normalized: list[str] = []
        pending_paragraph = False
        for line in lines:
            if line:
                if pending_paragraph and normalized:
                    normalized.append("")
                normalized.append(line)
                pending_paragraph = False
            elif normalized:
                pending_paragraph = True
        return "\n".join(normalized)


class _HTMLDescriptionSanitizer(HTMLParser):
    """Preserve safe publisher emphasis and structure for email rendering."""

    _PARAGRAPH = (
        '<p class="event-description-paragraph" '
        'style="margin:0 0 12px;color:#3c4043;font-size:15px;line-height:160%">'
    )
    _LIST = ' style="margin:0 0 12px;padding-left:22px;color:#3c4043;font-size:15px;line-height:160%"'
    _ITEM = ' style="margin:0 0 5px"'
    _LINK_STYLE = (
        'style="color:#174ea6;text-decoration:underline;'
        'text-decoration-color:#a8c7fa;text-underline-offset:3px"'
    )

    def __init__(self, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self._stack: list[tuple[str, str]] = []
        self._suppressed_depth = 0

    def _close_from(self, index: int) -> None:
        for _source_tag, output_tag in reversed(self._stack[index:]):
            self.parts.append(f"</{output_tag}>")
        del self._stack[index:]

    def _close_open_paragraph(self) -> None:
        matching_index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index][1] == "p"
            ),
            -1,
        )
        if matching_index >= 0:
            self._close_from(matching_index)

    def _ensure_text_container(self) -> None:
        if any(output_tag in {"p", "li"} for _source, output_tag in self._stack):
            return
        if any(output_tag in {"ul", "ol"} for _source, output_tag in self._stack):
            self.parts.append(f"<li{self._ITEM}>")
            self._stack.append(("__implicit_list_item__", "li"))
            return
        self.parts.append(self._PARAGRAPH)
        self._stack.append(("__implicit_paragraph__", "p"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._suppressed_depth:
            self._suppressed_depth += 1
            return
        if tag in {"script", "style"}:
            self._suppressed_depth = 1
            return
        if tag == "br":
            self._ensure_text_container()
            self.parts.append("<br>")
            return

        output_tag = ""
        if tag in {"p", "div"}:
            self._close_open_paragraph()
            output_tag = "p"
            self.parts.append(self._PARAGRAPH)
        elif tag in {"strong", "b"}:
            self._ensure_text_container()
            output_tag = "strong"
            self.parts.append("<strong>")
        elif tag in {"em", "i"}:
            self._ensure_text_container()
            output_tag = "em"
            self.parts.append("<em>")
        elif tag in {"ul", "ol"}:
            self._close_open_paragraph()
            output_tag = tag
            self.parts.append(f"<{tag}{self._LIST}>")
        elif tag == "li":
            self._close_open_paragraph()
            open_item_index = next(
                (
                    index
                    for index in range(len(self._stack) - 1, -1, -1)
                    if self._stack[index][1] == "li"
                ),
                -1,
            )
            if open_item_index >= 0:
                self._close_from(open_item_index)
            if not any(output in {"ul", "ol"} for _source, output in self._stack):
                self.parts.append(f"<ul{self._LIST}>")
                self._stack.append(("__implicit_list__", "ul"))
            output_tag = "li"
            self.parts.append(f"<li{self._ITEM}>")
        elif tag == "a":
            values = {key.lower(): value or "" for key, value in attrs}
            href = _safe_http_url(values.get("href", ""), self.base_url)
            if href:
                self._ensure_text_container()
                output_tag = "a"
                self.parts.append(
                    f'<a href="{html.escape(href, quote=True)}" {self._LINK_STYLE}>'
                )
        if output_tag:
            self._stack.append((tag, output_tag))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() != "br":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._suppressed_depth:
            self._suppressed_depth -= 1
            return
        if tag in {"p", "div"}:
            self._close_open_paragraph()
            return
        matching_index = next(
            (
                index
                for index in range(len(self._stack) - 1, -1, -1)
                if self._stack[index][0] == tag
            ),
            -1,
        )
        if matching_index < 0:
            return
        self._close_from(matching_index)

    def handle_data(self, data: str) -> None:
        if self._suppressed_depth:
            return
        if not data.strip() and not self._stack:
            return
        self._ensure_text_container()
        self.parts.append(html.escape(data))

    def rendered_html(self) -> str:
        if self._stack:
            self._close_from(0)
        return "".join(self.parts).strip()


def next_week_start(reference_date: date) -> date:
    """Return the next Monday, treating Monday itself as this week's start."""

    return reference_date + timedelta(days=(7 - reference_date.weekday()) % 7)


def normalize_child_name(value: object) -> str:
    """Return a bounded single-line display name safe for email subjects."""

    if not isinstance(value, str):
        raise ValueError("invalid_child_name")
    child_name = " ".join(value.split())
    if not child_name:
        raise ValueError("child_name_required")
    if len(child_name) > MAX_CHILD_NAME_LENGTH or any(
        ord(character) < 32 or ord(character) == 127 for character in child_name
    ):
        raise ValueError("invalid_child_name")
    return child_name


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


def source_age_categories_for_window(
    birth_date: date,
    start_date: date,
    end_date: date,
) -> tuple[str, ...]:
    """Return official age feeds that preserve useful publisher provenance.

    A minor's source plan includes every official child/teen category so an
    inclusive event remains discoverable even when the publisher assigned it a
    narrower category. At adulthood the plan follows only official categories
    whose local semantic windows overlap the person's age. A window crossing
    adulthood retains both sides automatically, so the plan advances without
    household-specific literals.
    """

    if end_date < start_date:
        raise ValueError("Source age-category window end cannot precede its start")
    categories = set(age_categories_for_window(birth_date, start_date, end_date))
    if age_in_months(birth_date, start_date) < ADULT_START_MONTHS:
        categories.update(MINOR_SOURCE_CATEGORIES)
    return tuple(category for category in AGE_CATEGORY_ORDER if category in categories)


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
DURATION_RES = (
    re.compile(
        r"\b(?:this|the)\s+"
        r"(?:event|program|class|session|storytime|workshop)\s+"
        r"(?:lasts?|runs?)\s+(?:for\s+)?(?P<minutes>\d{1,3})\s+minutes?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<minutes>\d{1,3})[- ]minute\s+"
        r"(?:event|program|class|session|storytime|workshop)\b",
        re.IGNORECASE,
    ),
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
        if start_meridiem := match.group("start_meridiem"):
            source_start = _clock_time(
                match.group("start_hour"),
                match.group("start_minute"),
                start_meridiem,
            )
        else:
            source_hour = int(match.group("start_hour"))
            source_minute = int(match.group("start_minute") or 0)
            published_hour = start_time.hour % 12 or 12
            source_start = (
                start_time
                if (source_hour, source_minute) == (published_hour, start_time.minute)
                else None
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
    start_at = datetime.combine(event_date, start_time)
    for pattern in DURATION_RES:
        if match := pattern.search(description):
            duration = timedelta(minutes=int(match.group("minutes")))
            if timedelta(minutes=15) <= duration <= timedelta(hours=8):
                return start_at + duration
    return None


def _repair_bare_numeric_entities(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        codepoint = int(match.group(1))
        is_valid_html_character = (
            codepoint in {9, 10, 13}
            or 32 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        )
        return chr(codepoint) if is_valid_html_character else match.group(0)

    return re.sub(r"(?<!&)#(\d{2,6});", replace, value)


def _description_data(
    raw_html: str,
    trailer: str,
    base_url: str = "",
) -> tuple[str, tuple[DescriptionLink, ...]]:
    extractor = _HTMLTextExtractor(base_url)
    extractor.feed(_repair_bare_numeric_entities(raw_html))
    extractor.close()
    value = html.unescape(extractor.text()).strip()
    if trailer and value.endswith(trailer):
        value = value[: -len(trailer)].rstrip()
    return value, tuple(extractor.links)


def _description_render_html(
    raw_html: str,
    trailer: str,
    base_url: str = "",
) -> str:
    """Return a small, email-safe subset of the publisher's description HTML."""

    sanitizer = _HTMLDescriptionSanitizer(base_url)
    sanitizer.feed(_repair_bare_numeric_entities(raw_html))
    sanitizer.close()
    value = sanitizer.rendered_html()
    if trailer:
        escaped_trailer = html.escape(trailer)
        trailer_index = value.rfind(escaped_trailer)
        if trailer_index >= 0 and re.fullmatch(
            r"(?:\s|</?(?:p|strong|em|ul|ol|li|a)(?:\s[^>]*)?>|<br>)*",
            value[trailer_index + len(escaped_trailer) :],
        ):
            value = (
                value[:trailer_index] + value[trailer_index + len(escaped_trailer) :]
            )
    value = re.sub(
        r'<p class="event-description-paragraph"[^>]*>\s*</p>',
        "",
        value,
    ).strip()
    if value and not re.search(r"<(?:p|ul|ol)\b", value):
        value = f"{_HTMLDescriptionSanitizer._PARAGRAPH}{value}</p>"
    return value


_VENUE_SUFFIX = (
    r"Park|Square|Playground|Garden|Museum|Community Center|Recreation Center|"
    r"Rec Center|School|Theater|Theatre|Studio|Gallery|Plaza|Courtyard|Field|"
    r"Pool|Market|Pavilion|Campus|Center"
)
_VENUE_NAME = rf"[A-Z][A-Za-z0-9&' .-]{{1,70}}?(?:{_VENUE_SUFFIX})"
_TITLE_VENUE_RE = re.compile(
    rf"\bat\s+(?P<venue>{_VENUE_NAME})\s*[!?.]*$",
    re.IGNORECASE,
)
_DESCRIPTION_VENUE_RES = (
    re.compile(
        rf"\b(?:will take|takes) place at\s+(?P<venue>{_VENUE_NAME})\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\bjoin us in\s+(?P<venue>{_VENUE_NAME})\b", re.IGNORECASE),
    re.compile(rf"\bmeet us at\s+(?P<venue>{_VENUE_NAME})\b", re.IGNORECASE),
    re.compile(rf"\blocated at\s+(?P<venue>{_VENUE_NAME})\b", re.IGNORECASE),
)
_ROOM_RES = (
    re.compile(
        r"\b(?:[Tt]he|[Oo]ur)[ \t]+"
        r"(?P<room>[A-Z][A-Za-z0-9&' -]{1,60}[ \t]+"
        r"(?:Room|Auditorium|Department|Center|Studio|Gallery|Courtyard|Pavilion))\b"
    ),
    re.compile(r"\b(?P<room>Room[ \t]+(?:[A-Z]|\d{1,4}[A-Za-z]?))\b"),
    re.compile(
        r"\b(?P<room>(?:first|second|third|fourth|fifth|lower|ground)[ -]floor"
        r"(?:[ A-Za-z0-9&'-]{0,40})?)\b",
        re.IGNORECASE,
    ),
)


def explicit_venue(title: str, description: str) -> str:
    """Return a confidently named off-site venue from published event text."""

    if match := _TITLE_VENUE_RE.search(title):
        if venue := _named_venue(match.group("venue")):
            return venue
    for pattern in _DESCRIPTION_VENUE_RES:
        if match := pattern.search(description):
            if venue := _named_venue(match.group("venue")):
                return venue
    return ""


def _named_venue(value: str) -> str:
    """Reject generic location phrases matched by case-insensitive lead-in text."""

    venue = value.strip()
    if not venue:
        return ""
    first_word = venue.split(maxsplit=1)[0]
    if not venue[0].isupper() or first_word.lower() in {"a", "an", "our", "the"}:
        return ""
    return venue


def explicit_room(description: str) -> str:
    """Return a specifically named room, excluding generic room references."""

    for pattern in _ROOM_RES:
        if match := pattern.search(description):
            return match.group("room").strip()
    return ""


def clean_title(raw_title: str, branch: Branch) -> str:
    value = re.sub(r"^\d{2}/\d{2}/\d{2}:\s*", "", raw_title.strip())
    suffix = f" - {branch.name}"
    if value.endswith(suffix):
        value = value[: -len(suffix)]
    value = re.sub(r"\bBaby\s{2,}Toddler\b", "Baby & Toddler", value)
    value = value.replace("Storytime  Playgroup", "Storytime & Playgroup").strip()
    return value or "Library event"


_ONLINE_EVENT_RE = re.compile(
    r"\b(?:virtual|online)\s+(?:event|program|class|session|workshop|storytime)\b|"
    r"\b(?:via|on)\s+Zoom\b|\bjoin us online\b",
    re.IGNORECASE,
)
_IN_PERSON_EVENT_RE = re.compile(
    r"\bin[ -]person\b|\b(?:at|inside)\s+the\s+library\b",
    re.IGNORECASE,
)


def event_modality(
    title: str, description: str
) -> Literal["in_person", "online", "hybrid"]:
    """Return modality only when the publisher uses explicit event wording."""

    searchable = f"{title}\n{description}"
    if re.search(r"\bhybrid\b", searchable, re.IGNORECASE) or (
        _ONLINE_EVENT_RE.search(searchable) and _IN_PERSON_EVENT_RE.search(searchable)
    ):
        return "hybrid"
    if _ONLINE_EVENT_RE.search(searchable):
        return "online"
    return "in_person"


def clean_image_url(raw_url: str, base_url: str = "") -> str:
    """Return a publisher-hosted HTTPS image URL."""

    value = raw_url.strip().replace("\\", "/")
    if not value:
        return ""
    url = _safe_http_url(value, base_url)
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return url if parsed.scheme == "https" and hostname in TRUSTED_IMAGE_HOSTS else ""


def parse_feed(
    xml_content: bytes | str,
    branch: Branch,
    age_category: str | None = None,
) -> tuple[list[Event], int]:
    """Parse one official branch RSS feed."""

    root = ET.fromstring(xml_content)
    items = root.findall("./channel/item")
    events: list[Event] = []
    for item in items[:MAX_PARSED_RSS_ITEMS]:
        start_date_text = (item.findtext("startdate") or "").strip()
        start_time_text = (item.findtext("starttime") or "").strip()
        if not start_date_text or not start_time_text:
            continue
        try:
            event_date = datetime.strptime(start_date_text, "%m/%d/%y").date()
            normalized_time = start_time_text.replace(".", "").strip()
            start_time = datetime.strptime(normalized_time, "%I:%M %p").time()
        except (TypeError, ValueError):
            continue
        link = _safe_http_url(item.findtext("link") or "") or _safe_http_url(
            item.findtext("guid") or ""
        )
        trailer = f"{start_date_text}, {start_time_text} - {branch.name}"
        raw_description = item.findtext("description") or ""
        description, description_links = _description_data(
            raw_description,
            trailer,
            link or branch.calendar_url,
        )
        description_html = _description_render_html(
            raw_description,
            trailer,
            link or branch.calendar_url,
        )
        title = clean_title(item.findtext("title") or "Library event", branch)
        if (
            len(title) > MAX_EVENT_TITLE_LENGTH
            or len(description) > MAX_EVENT_DESCRIPTION_LENGTH
            or len(description_links) > MAX_DESCRIPTION_LINKS
        ):
            continue
        events.append(
            Event(
                title=title,
                event_date=event_date,
                start_time=start_time,
                description=description,
                link=link,
                image_url=clean_image_url(
                    item.findtext("eventimage") or "", branch.rss_url
                ),
                branch=branch,
                age_categories=(age_category,) if age_category else (),
                end_at=explicit_end_at(event_date, start_time, description),
                description_links=description_links,
                description_html=description_html,
                venue=explicit_venue(title, description),
                room=explicit_room(description),
                modality=event_modality(title, description),
            )
        )
    return events, len(items)


def merge_events(events: Sequence[Event]) -> list[Event]:
    """Deduplicate events while preserving every official age classification."""

    merged: dict[str, Event] = {}
    for event in events:
        key = event_identity(event)
        if existing := merged.get(key):
            age_categories = tuple(
                sorted(
                    {*existing.age_categories, *event.age_categories},
                    key=lambda category: AGE_CATEGORY_ORDER.get(category, 999),
                )
            )
            description_links = tuple(
                dict.fromkeys((*existing.description_links, *event.description_links))
            )
            richer_description_event = max(
                (existing, event),
                key=lambda candidate: (
                    len(candidate.description),
                    bool(candidate.description_html),
                    len(candidate.description_html),
                ),
            )
            merged[key] = replace(
                existing,
                description=richer_description_event.description,
                image_url=existing.image_url or event.image_url,
                age_categories=age_categories,
                end_at=existing.end_at or event.end_at,
                description_links=description_links,
                description_html=richer_description_event.description_html,
                venue=existing.venue or event.venue,
                room=existing.room or event.room,
            )
        else:
            merged[key] = event
    return list(merged.values())


def event_identity(event: Event) -> str:
    """Return a stable occurrence identity, including for recurring series URLs."""

    source = event.link or event.title
    return (
        f"{source}:{event.branch.code}:{event.event_date.isoformat()}:"
        f"{event.start_time.isoformat()}"
    )


INACTIVE_TITLE_RE = re.compile(
    r"\b(?:cancelled|canceled|postponed|rescheduled)\b",
    re.IGNORECASE,
)


def event_is_active(event: Event) -> bool:
    """Return whether an event title still presents an actionable occurrence."""

    return INACTIVE_TITLE_RE.search(event.title) is None


AGE_RANGE_RE = re.compile(
    r"\bages?\s*(?P<low>\d+)\s*"
    r"(?P<low_unit>months?|mos?|years?|yrs?)?\s*"
    r"(?:-|\u2013|to|through)\s*(?P<high>\d+)\s*"
    r"(?P<high_unit>months?|mos?|years?|yrs?)?\b",
    re.IGNORECASE,
)
NEWBORN_RANGE_RE = re.compile(
    r"\b(?:children\s+from\s+)?(?:newborns?|birth)\s*"
    r"(?:-|\u2013|to|through)\s*(?:age\s*)?(?P<high>\d+)\s*"
    r"(?P<high_unit>months?|mos?|years?|yrs?)?\b",
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
    match = NEWBORN_RANGE_RE.search(text)
    if match:
        high_unit = match.group("high_unit")
        high = _to_months(int(match.group("high")), high_unit)
        margin = (
            1 if high_unit and high_unit.lower().startswith(("month", "mo")) else 12
        )
        return "best" if child_months < high + margin else "exclude"

    match = AGE_RANGE_RE.search(text)
    if match:
        low_unit = match.group("low_unit") or match.group("high_unit")
        high_unit = match.group("high_unit") or match.group("low_unit")
        low = _to_months(int(match.group("low")), low_unit)
        high = _to_months(int(match.group("high")), high_unit)
        margin = (
            1 if high_unit and high_unit.lower().startswith(("month", "mo")) else 12
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

    if child_months < 216 and any(
        term in text
        for term in (
            "all children can",
            "all children are welcome",
            "all kids can",
            "all kids are welcome",
        )
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

    # A published category remains stronger than generic title inference, but
    # explicit inclusive language above can correct a category that is too
    # narrow for the event's own description.
    if event.age_categories:
        return "exclude"

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

    relevant_events = merge_events(
        [
            event
            for event in events
            if start_date <= event.event_date <= end_date and event_is_active(event)
        ]
    )

    rank_order = {"best": 0, "good": 1, "possible": 2, "broad": 3}
    included: list[tuple[Event, FitRank]] = []
    for event in relevant_events:
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
    if re.search(r"\b(?:read(?:ing)?|story(?:time)?|books?)\b", text):
        return "\U0001f4da"
    if re.search(r"\b(?:music|sing(?:ing)?|karaoke)\b", text):
        return "\U0001f3b5"
    if re.search(r"\b(?:crafts?|origami|art)\b", text):
        return "\U0001f3a8"
    if re.search(r"\b(?:playgroup|play group|playtime)\b", text):
        return "\U0001f9f8"
    return "\N{SPARKLES}"


def event_location_name(event: Event) -> str:
    """Return the most specific confidently published location name."""

    if event.modality == "online":
        return "Online"
    return event.venue or event.branch.name


def event_location_label(event: Event) -> str:
    """Return only the place and room represented by the map destination."""

    location = event_location_name(event)
    if event.modality == "online":
        return location
    location = f"{location} {MIDDLE_DOT} {event.room}" if event.room else location
    if event.modality == "hybrid":
        location += f" {MIDDLE_DOT} Online option"
    return location


def event_location_summary(event: Event) -> str:
    """Return the visible venue, room, and off-site hosting context."""

    summary = event_location_label(event)
    if event.venue and event.modality != "online":
        summary += f" {MIDDLE_DOT} Hosted by {event.branch.name}"
    return summary


def event_calendar_location(event: Event) -> str:
    """Return a geocodable calendar location without a redundant email address."""

    if event.modality == "online":
        return "Online"
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
    end = event.end_at or event.starts_at + timedelta(minutes=duration_minutes)
    detail_parts = (
        []
        if compact
        else [
            _bounded_text(event.description, MAX_CALENDAR_DETAILS_CHARS),
            *related_link_lines(event),
        ]
    )
    details = "\n\n".join(part for part in detail_parts if part)
    details += f"\n\nOfficial event details: {event_details_url(event)}"
    if event.end_at is None:
        details += (
            "\n\nThe library did not publish an end time. "
            f"The {duration_minutes}-minute duration is a calendar placeholder."
        )
    parameters = {
        "action": "TEMPLATE",
        "text": _bounded_text(event.title, MAX_DISPLAY_TITLE_LENGTH),
        "dates": f"{event.starts_at:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}",
        "ctz": TIMEZONE,
        "location": event_calendar_location(event),
        "details": details,
    }
    base = "https://calendar.google.com/calendar/render?"
    url = base + urllib.parse.urlencode(parameters)
    while len(url) > MAX_CALENDAR_URL_LENGTH and parameters["details"]:
        overflow = len(url) - MAX_CALENDAR_URL_LENGTH
        target = max(0, len(parameters["details"]) - overflow - 32)
        parameters["details"] = _bounded_text(parameters["details"], target)
        url = base + urllib.parse.urlencode(parameters)
    return url


def directions_url(branch: Branch) -> str:
    return "https://www.google.com/maps/search/?" + urllib.parse.urlencode(
        {"api": "1", "query": f"{branch.name}, {branch.address}"}
    )


def event_directions_url(event: Event) -> str:
    """Return a map link for an explicit venue or the hosting branch."""

    if event.modality == "online":
        return ""
    if not event.venue:
        return directions_url(event.branch)
    return "https://www.google.com/maps/search/?" + urllib.parse.urlencode(
        {"api": "1", "query": f"{event.venue}, Philadelphia, PA"}
    )


def _bounded_text(value: str, maximum: int) -> str:
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
            'style="color:#174ea6;text-decoration:underline;'
            'text-decoration-color:#a8c7fa;text-underline-offset:3px">'
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


def _event_chip_specs(event: Event) -> tuple[tuple[str, str], ...]:
    """Return bounded, prioritized highlights provable from publisher wording."""

    topic_chips: list[tuple[str, str]] = []
    logistics_chips: list[tuple[str, str]] = []
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
        if re.search(source_pattern, searchable, re.IGNORECASE) and not re.search(
            title_pattern, event.title, re.IGNORECASE
        ):
            topic_chips.append(("topic", label))
    if re.search(r"\b(?:outdoor|outdoors|outside)\b", searchable, re.IGNORECASE) or (
        event.venue
        and re.search(
            r"\b(?:park|square|playground|garden)\b",
            event.venue,
            re.IGNORECASE,
        )
    ):
        logistics_chips.append(("logistics", "Outdoors"))
    take_home_craft = re.search(
        r"\b(?:to-go|take[ -]home)\s+(?:a\s+)?craft\b",
        searchable,
        re.IGNORECASE,
    )
    if take_home_craft:
        topic_chips = [chip for chip in topic_chips if chip != ("topic", "Crafts")]
        logistics_chips.append(("logistics", "Take-home craft"))
    if re.search(r"\bsiblings? (?:are )?welcome\b", searchable, re.IGNORECASE):
        logistics_chips.append(("logistics", "Siblings welcome"))
    if re.search(
        r"\b(?:kids|children) of all ages\b|\beven the littlest\b",
        searchable,
        re.IGNORECASE,
    ):
        logistics_chips.append(("logistics", "All ages welcome"))
    elif (
        re.search(r"\brange of ages\b", searchable, re.IGNORECASE)
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
    weather_warning = re.search(
        r"\b(?:unfavorable|inclement|cooler|warmer) weather\b|"
        r"\bweather permitting\b|\bweather[^.]{0,45}\bcancel",
        searchable,
        re.IGNORECASE,
    )
    weather_negated = re.search(
        r"\b(?:will|does|do) not be cancelled for weather\b|"
        r"\bregardless of (?:the )?weather\b",
        searchable,
        re.IGNORECASE,
    )
    if weather_warning and not weather_negated:
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

    if re.search(r"\b(?:drop[ -]?in|walk[ -]?ins? welcome)\b", searchable, re.I):
        logistics_chips.append(("logistics", "Drop-in"))
    if re.search(
        r"\b(?:materials?|supplies) (?:are |will be )?provided\b",
        searchable,
        re.I,
    ) and not re.search(
        r"\b(?:materials?|supplies) (?:are |will be )?not provided\b",
        searchable,
        re.I,
    ):
        logistics_chips.append(("logistics", "Materials provided"))
    if re.search(
        r"\b(?:caregiver|parent|adult) (?:participation|participates?|joins?)\b|"
        r"\bwith (?:a |their )?(?:caregiver|parent|adult)\b",
        searchable,
        re.I,
    ):
        logistics_chips.append(("logistics", "Caregiver participation"))
    if re.search(r"\bsensory[ -]friendly\b", searchable, re.I):
        logistics_chips.append(("logistics", "Sensory-friendly"))
    if re.search(
        r"\bASL (?:interpretation|interpreter|interpreted)\b", searchable, re.I
    ):
        logistics_chips.append(("logistics", "ASL interpreted"))
    if re.search(
        r"\bbilingual\b|\b(?:English|Spanish)\s*(?:and|/)\s*(?:English|Spanish)\b",
        searchable,
        re.I,
    ):
        logistics_chips.append(("logistics", "Bilingual"))

    action_priority = {
        "Registration required": 0,
        "Weather dependent": 1,
        "Limited supplies": 2,
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
        for kind, label in _event_chip_specs(event)
    )
    return f'<div style="margin:8px 0 0">{chips}</div>' if chips else ""


def _event_age_categories(event: Event) -> tuple[str, ...]:
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
    categories = _event_age_categories(event)
    if not categories:
        return ""
    audience = f" {MIDDLE_DOT} ".join(html.escape(category) for category in categories)
    return (
        '<div class="event-audience" style="margin:10px 0 0;color:#5f6368;'
        'font-size:14px;line-height:145%"><strong>Listed for:</strong> '
        f"{audience}</div>"
    )


def _button(label: str, url: str, primary: bool = False) -> str:
    background = "#1967d2" if primary else "#ffffff"
    color = "#ffffff" if primary else "#1967d2"
    return (
        '<table class="email-button" role="presentation" border="0" '
        'cellpadding="0" cellspacing="0" '
        'style="border-collapse:separate;margin:12px 0 0">'
        f'<tr><td bgcolor="{background}" style="padding:11px 15px;'
        f'border:1px solid #1967d2;border-radius:8px;background:{background}">'
        f'<a href="{html.escape(url, quote=True)}" style="display:block;'
        f"color:{color};font-weight:700;text-decoration:none;font-size:14px;"
        f'line-height:140%">{html.escape(label)}</a></td></tr></table>'
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

    if source_warnings or source_errors:
        return [
            (
                "Some library listings may be missing. "
                "Check the full branch calendars below.",
                True,
            )
        ]
    return []


def _calendar_placeholder_note(events: Sequence[Event], duration_minutes: int) -> str:
    """Return one precise note for Google links that need placeholder end times."""

    missing_count = sum(event.end_at is None for event in events)
    if not missing_count:
        return ""
    if missing_count == len(events):
        opening = "The library did not publish end times for these activities"
    else:
        opening = "Some end times are not published"
    return (
        f"{opening}; Google Calendar uses a {duration_minutes}-minute "
        "placeholder for those activities."
    )


def _render_event_card(
    event: Event,
    *,
    duration_minutes: int,
    compact: bool = False,
) -> str:
    event_url = html.escape(event_details_url(event), quote=True)
    display_title = _bounded_text(event.title, MAX_DISPLAY_TITLE_LENGTH)
    if compact:
        location_label = html.escape(event_location_label(event))
        directions = event_directions_url(event)
        location_html = (
            f'<a href="{html.escape(directions, quote=True)}" '
            'style="color:#202124;text-decoration:underline">'
            f"{location_label}</a>"
            if directions
            else location_label
        )
        calendar_url = html.escape(
            google_calendar_url(event, duration_minutes, compact=True), quote=True
        )
        return f"""
    <table class="event-card-shell compact-event-card" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">
    <tr><td bgcolor="#ffffff" style="padding:14px 18px 15px;background:#ffffff;border:1px solid #e3e7ee;border-radius:12px;overflow-wrap:anywhere;word-break:break-word">
      <h3 style="margin:0 0 5px;color:#202124;font-size:19px;line-height:130%"><span aria-hidden="true">{icon_for(event)}</span> <a href="{event_url}" style="color:#174ea6;text-decoration:underline">{html.escape(display_title)}</a></h3>
      <div style="font-size:14px;font-weight:700;color:#202124;line-height:145%">{format_event_time(event)} {MIDDLE_DOT} {location_html}</div>
      {_event_audience_html(event)}
      {_event_chips_html(event)}
      <div style="margin:10px 0 0;font-size:13px;font-weight:700"><a href="{calendar_url}" style="color:#1967d2;text-decoration:underline">Add to Google Calendar</a></div>
    </td></tr><tr><td height="10" style="height:10px;font-size:1px;line-height:10px">&nbsp;</td></tr>
    </table>
    """
    image_cell = ""
    hero_image = ""
    if event.image_url and not compact and event.image_layout == "hero":
        hero_image = (
            '<tr><td class="event-hero-image-cell" colspan="2" style="padding:0;'
            'background:#ffffff;text-align:center">'
            f'<a href="{event_url}" style="display:block;width:100%;text-decoration:none">'
            f'<img width="638" src="{html.escape(event.image_url, quote=True)}" '
            f'alt="View official event details for {html.escape(display_title, quote=True)}" '
            'style="display:block;width:100%;max-width:638px;height:auto;margin:0 auto;'
            'border:0"></a></td></tr>'
        )
    elif event.image_url and not compact:
        image_cell = (
            '<td class="event-image-cell" width="190" valign="top" '
            'style="width:190px;padding:0;background:#ffffff;text-align:center">'
            f'<a href="{event_url}" style="display:block;width:100%;'
            'text-decoration:none">'
            f'<img width="190" src="{html.escape(event.image_url, quote=True)}" '
            f'alt="View official event details for '
            f'{html.escape(display_title, quote=True)}" '
            'style="display:block;width:100%;max-width:190px;height:auto;'
            'margin:0 auto;border:0;object-fit:contain"></a></td>'
        )
    heading_colspan = "" if image_cell else ' colspan="2"'
    location_label = html.escape(event_location_label(event))
    host_context = (
        f" {MIDDLE_DOT} Hosted by {html.escape(event.branch.name)}"
        if event.venue and event.modality != "online"
        else ""
    )
    directions = event_directions_url(event)
    if directions:
        location_html = (
            f'<a href="{html.escape(directions, quote=True)}" '
            'style="color:#202124;text-decoration:underline;'
            'text-decoration-color:#c4c7c5;text-underline-offset:3px">'
            f"{location_label}</a>"
        )
    else:
        location_html = location_label
    shortened_note = ""
    if event.description_truncated:
        shortened_note = (
            '<p style="margin:8px 0 0;color:#5f6368;font-size:13px;line-height:150%">'
            f'Description shortened for email. <a href="{event_url}" '
            'style="color:#174ea6">View the complete official listing</a>.</p>'
        )
    body = f"""
      <tr>
      <td class="event-body-cell" colspan="2" style="padding:16px 20px 18px;border-top:1px solid #eef1f5;overflow-wrap:anywhere;word-break:break-word">
        <div>{_description_paragraphs_html(event)}</div>
        {shortened_note}
        {_button("Add to Google Calendar", google_calendar_url(event, duration_minutes), primary=True)}
      </td>
      </tr>"""
    return f"""
    <table class="event-card-shell" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">
    <tr><td style="padding:0 0 12px">
      <table class="event-card-table" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#ffffff" style="width:100%;border-collapse:separate;border-spacing:0;background:#ffffff;border:1px solid #e3e7ee;border-radius:14px;overflow:hidden">
      {hero_image}
      <tr>
      {image_cell}
      <td class="event-heading-cell"{heading_colspan} valign="top" style="padding:16px 20px 14px;overflow-wrap:anywhere;word-break:break-word">
        <h3 style="margin:0 0 6px;color:#202124;font-size:22px;line-height:125%"><span aria-hidden="true">{icon_for(event)}</span> <a href="{event_url}" style="color:#174ea6;text-decoration:underline;text-decoration-color:#a8c7fa;text-underline-offset:3px">{html.escape(display_title)}</a></h3>
        <div style="font-size:16px;font-weight:700;color:#202124;line-height:145%">{format_event_time(event)} {MIDDLE_DOT} {location_html}{host_context}</div>
        {_event_audience_html(event)}
        {_event_chips_html(event)}
      </td>
      </tr>
      {body}
      </table>
    </td></tr>
    </table>
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
    full_event_ids: frozenset[str] | None = None,
    email_omitted_count: int = 0,
) -> str:
    if full_event_ids is None:
        full_event_ids = frozenset(event_identity(event) for event in events)
    day_sections: list[str] = []
    for event_date, day_items in groupby(events, key=lambda event: event.event_date):
        day_cards = "".join(
            _render_event_card(
                event,
                duration_minutes=duration_minutes,
                compact=event_identity(event) not in full_event_ids,
            )
            for event in day_items
        )
        day_sections.append(
            f"""
            <table class="event-day-heading" role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">
              <tr><td style="padding:0 4px 10px"><h2 style="margin:0;color:#174ea6;font-size:20px;font-weight:800;line-height:130%">{event_date:%A, %B} {event_date.day}</h2></td></tr>
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
    if email_omitted_count:
        source_note_parts.append(
            '<p style="margin:8px 0 0;color:#5f6368">'
            f"{email_omitted_count} additional matched "
            f"activit{'y was' if email_omitted_count == 1 else 'ies were'} omitted "
            "to keep this email reliable. See the full calendars below.</p>"
        )
    source_note = "".join(source_note_parts)
    calendar_note_text = _calendar_placeholder_note(events, duration_minutes)
    calendar_note = ""
    if calendar_note_text:
        calendar_note = (
            '<p style="margin:8px 0 0;color:#5f6368">'
            f"{html.escape(calendar_note_text)}</p>"
        )
    preheader = (
        "See dates, locations, age listings, planning notes, and Google Calendar links."
        if events
        else (
            "No clearly age-matched activities were published; "
            "check the full branch calendars."
        )
    )

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light"><title>Library fun for {html.escape(child_name)}</title>
<style>
html,body {{color-scheme:light only}}
@media only screen and (max-width:620px) {{
  .event-image-cell,.event-heading-cell,.event-body-cell {{display:block!important;width:auto!important;max-width:100%!important}}
  .event-image-cell {{padding:0!important;text-align:center!important}}
  .event-image-cell img {{width:100%!important;max-width:360px!important;margin:0 auto!important}}
  .event-hero-image-cell img {{width:100%!important;max-width:100%!important;height:auto!important}}
  .event-heading-cell {{padding:16px 18px 14px!important}}
  .event-body-cell {{padding:16px 18px 18px!important}}
}}
</style></head>
<body style="margin:0;padding:0;background:#f3f6fb;font-family:Arial,Helvetica,sans-serif;color:#202124">
  <div style="display:none!important;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all">{html.escape(preheader)}&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;</div>
  <table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="#f3f6fb" style="width:100%;border-collapse:collapse;background:#f3f6fb"><tr><td align="center" style="padding:20px 10px">
    <table role="presentation" width="680" border="0" cellpadding="0" cellspacing="0" style="width:100%;max-width:680px;border-collapse:collapse">
      <tr><td style="padding:24px 24px 20px;background:#174ea6;border-radius:16px 16px 0 0;color:#ffffff">
        <div style="font-size:13px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;opacity:.85">{_format_week_range(week_start, week_end)}</div>
        <h1 style="margin:8px 0 8px;font-size:30px;line-height:120%"><span aria-hidden="true">&#128218;</span> Library fun for {html.escape(child_name)}</h1>
        <p style="margin:0;font-size:16px;line-height:150%">{html.escape(intro)}</p>
      </td></tr>
      <tr><td style="padding:22px 0">{body}</td></tr>
      <tr><td style="padding:18px 20px;background:#ffffff;border-radius:12px;color:#5f6368;font-size:13px;line-height:155%">
        {source_note}
        <strong style="color:#3c4043">See every published event:</strong> {branch_links}
        <p style="margin:8px 0 0">Library schedules can change, so check the official event page before leaving.</p>
        {calendar_note}
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
            chip_labels = [label for _kind, label in _event_chip_specs(event)]
            age_categories = _event_age_categories(event)
            lines.extend(
                [
                    f"{format_event_time(event)} | {event.title}",
                    f"{event_location_summary(event)}: {event_directions_url(event)}",
                    *(
                        [f"Listed for: {f' {MIDDLE_DOT} '.join(age_categories)}"]
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
                    f"Add to Google Calendar: {google_calendar_url(event, duration_minutes)}",
                    f"Event details: {event_details_url(event)}",
                    "",
                ]
            )
    plain_source_notes = [
        note for note, _ in _source_notes(source_errors, source_warnings)
    ]
    if plain_source_notes:
        lines.extend(plain_source_notes)
    lines.extend(["", "Full branch calendars:"])
    lines.extend(f"- {branch.name}: {branch.calendar_url}" for branch in branches)
    calendar_note = _calendar_placeholder_note(events, duration_minutes)
    if calendar_note:
        lines.extend(["", calendar_note])
    lines.extend(
        [
            "",
            "Library schedules can change, so check the official event page before leaving.",
        ]
    )
    return "\n".join(lines)


def select_digest_events(
    events: Sequence[Event],
    *,
    birth_date: date,
    filter_mode: str,
    week_start: date,
    week_end: date,
) -> tuple[list[Event], list[Event]]:
    """Return active weekly occurrences and the age-matched subset."""

    weekly_events = merge_events(
        [
            event
            for event in events
            if week_start <= event.event_date <= week_end and event_is_active(event)
        ]
    )
    return weekly_events, matching_events(
        weekly_events,
        birth_date,
        filter_mode,
        week_start,
        week_end,
    )


def _display_event(event: Event) -> Event:
    """Return an email-bounded event while preserving source data upstream."""

    title = _bounded_text(event.title, MAX_DISPLAY_TITLE_LENGTH)
    description = _bounded_text(event.description, MAX_CARD_DESCRIPTION_CHARS)
    truncated = description != " ".join(event.description.split())
    return replace(
        event,
        title=title,
        description=description,
        description_html="" if truncated else event.description_html,
        description_truncated=truncated,
    )


def _distance_priority(
    event: Event,
    distance_by_branch_code: Mapping[str, float],
) -> tuple[float, datetime, str, str]:
    distance = distance_by_branch_code.get(event.branch.code, float("inf"))
    return distance, event.starts_at, event.branch.name, event.title


def _render_budgeted_html(
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
    distance_by_branch_code: Mapping[str, float],
    initially_omitted_count: int,
) -> tuple[str, list[Event], frozenset[str], int]:
    """Fit rich cards into a safe HTML budget, favoring nearby branches."""

    rendered_events = list(events)
    priority = sorted(
        rendered_events,
        key=lambda event: _distance_priority(event, distance_by_branch_code),
    )
    omitted_count = initially_omitted_count

    def render(full_ids: frozenset[str]) -> str:
        return _render_html(
            rendered_events,
            child_name=child_name,
            birth_date=birth_date,
            week_start=week_start,
            week_end=week_end,
            branches=branches,
            duration_minutes=duration_minutes,
            source_errors=source_errors,
            source_warnings=source_warnings,
            full_event_ids=full_ids,
            email_omitted_count=omitted_count,
        )

    compact_html = render(frozenset())
    while len(compact_html.encode("utf-8")) > MAX_DIGEST_HTML_BYTES and rendered_events:
        removed = priority.pop()
        rendered_events.remove(removed)
        omitted_count += 1
        compact_html = render(frozenset())

    html_bytes = len(compact_html.encode("utf-8"))
    if priority:
        nearest = priority[0]
        nearest_delta = len(
            _render_event_card(
                nearest, duration_minutes=duration_minutes, compact=False
            ).encode("utf-8")
        ) - len(
            _render_event_card(
                nearest, duration_minutes=duration_minutes, compact=True
            ).encode("utf-8")
        )
        while len(priority) > 1 and html_bytes + nearest_delta > MAX_DIGEST_HTML_BYTES:
            removed = priority.pop()
            rendered_events.remove(removed)
            omitted_count += 1
            compact_html = render(frozenset())
            html_bytes = len(compact_html.encode("utf-8"))

    full_ids: set[str] = set()
    for event in priority:
        identity = event_identity(event)
        compact_card = _render_event_card(
            event, duration_minutes=duration_minutes, compact=True
        )
        full_card = _render_event_card(
            event, duration_minutes=duration_minutes, compact=False
        )
        delta = len(full_card.encode("utf-8")) - len(compact_card.encode("utf-8"))
        if html_bytes + delta <= MAX_DIGEST_HTML_BYTES:
            full_ids.add(identity)
            html_bytes += delta

    frozen_ids = frozenset(full_ids)
    rendered = render(frozen_ids)
    return rendered, rendered_events, frozen_ids, omitted_count


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
    supplemental_age_failures: Sequence[str] = (),
    supplemental_age_limitations: Sequence[str] = (),
    image_url_overrides: Mapping[str, str] | None = None,
    image_layout_overrides: Mapping[str, Literal["side", "hero"]] | None = None,
    distance_by_branch_code: Mapping[str, float] | None = None,
) -> dict[str, object]:
    """Build the complete JSON-serializable email response."""

    child_name = normalize_child_name(child_name)
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
    weekly_events, included = select_digest_events(
        events,
        birth_date=birth_date,
        filter_mode=filter_mode,
        week_start=week_start,
        week_end=week_end,
    )
    source_included = included
    included = [
        replace(
            _display_event(event),
            image_url=(
                image_url_overrides.get(event_identity(event), "")
                if image_url_overrides is not None
                else event.image_url
            ),
            image_layout=(
                image_layout_overrides.get(event_identity(event), "side")
                if image_layout_overrides is not None
                else event.image_layout
            ),
        )
        for event in included
    ]
    distances = distance_by_branch_code or {}
    budget_priority = sorted(
        included,
        key=lambda event: _distance_priority(event, distances),
    )
    initially_omitted_count = max(0, len(budget_priority) - MAX_EMAIL_EVENTS)
    if initially_omitted_count:
        kept_identities = {
            event_identity(event) for event in budget_priority[:MAX_EMAIL_EVENTS]
        }
        included = [
            event for event in included if event_identity(event) in kept_identities
        ]
    rendered_html, email_events, full_event_ids, email_omitted_count = (
        _render_budgeted_html(
            included,
            child_name=child_name,
            birth_date=birth_date,
            week_start=week_start,
            week_end=week_end,
            branches=selected_branches,
            duration_minutes=duration_minutes,
            source_errors=source_errors,
            source_warnings=source_warnings,
            distance_by_branch_code=distances,
            initially_omitted_count=initially_omitted_count,
        )
    )
    subject = (
        f"{len(source_included)} library "
        f"activit{'y' if len(source_included) == 1 else 'ies'} "
        f"for {child_name} this week \U0001f4da | {_subject_week_range(week_start, week_end)}"
    )
    return {
        "subject": subject,
        "message": _render_plain_text(
            email_events,
            child_name=child_name,
            birth_date=birth_date,
            week_start=week_start,
            week_end=week_end,
            branches=selected_branches,
            duration_minutes=duration_minutes,
            source_errors=source_errors,
            source_warnings=source_warnings,
        ),
        "html": rendered_html,
        "metadata": {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "filter_mode": filter_mode,
            "scanned_count": len(weekly_events),
            "included_count": len(source_included),
            "omitted_count": len(weekly_events) - len(source_included),
            "included_event_ids": [
                event.link.rsplit("/", 1)[-1] if event.link else event_identity(event)
                for event in source_included
            ],
            "html_bytes": len(rendered_html.encode("utf-8")),
            "full_card_count": len(full_event_ids),
            "compact_card_count": len(email_events) - len(full_event_ids),
            "email_omitted_count": email_omitted_count,
            "truncated_description_count": sum(
                event.description_truncated for event in email_events
            ),
            "distance_priority_used": bool(distances)
            and (len(full_event_ids) < len(source_included) or email_omitted_count > 0),
            "full_card_event_ids": [
                event_identity(event)
                for event in email_events
                if event_identity(event) in full_event_ids
            ],
            "source_counts": dict(source_counts),
            "source_errors": list(source_errors),
            "source_warnings": list(source_warnings),
            "supplemental_age_failures": list(supplemental_age_failures),
            "supplemental_age_limitations": list(supplemental_age_limitations),
        },
    }
