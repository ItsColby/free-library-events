"""Free Library event model, feed parsing, and event normalization."""

from __future__ import annotations

import calendar
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Literal

TIMEZONE = "America/New_York"
FILTER_MODES = ("Strict", "Recommended", "Broad")
EN_DASH = "\N{EN DASH}"
MAX_CHILD_NAME_LENGTH = 80
MAX_DESCRIPTION_LINKS = 50
MAX_EVENT_DESCRIPTION_LENGTH = 50_000
MAX_EVENT_TITLE_LENGTH = 500
MAX_PARSED_RSS_ITEMS = 100
MAX_URL_LENGTH = 2_048
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
        address="932 South 7th Street, Philadelphia, PA 19147-2932",
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
    weather_location_conditional: bool = False
    display_highlights: tuple[tuple[str, str], ...] | None = None

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
    def __init__(self, base_url: str) -> None:
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


class HTMLDescriptionSanitizer(HTMLParser):
    """Preserve safe publisher emphasis and structure for email rendering."""

    _PARAGRAPH = (
        '<p class="event-description-paragraph" '
        'style="margin:0 0 12px;color:#3c4043;font-size:15px;line-height:160%">'
    )
    _LIST = (
        ' class="event-description-list" '
        'style="margin:0 0 12px;padding-left:22px;color:#3c4043;'
        'font-size:15px;line-height:160%"'
    )
    _ITEM = ' style="margin:0 0 5px"'
    _LINK_STYLE = (
        'style="color:#174ea6;text-decoration:underline;'
        'text-decoration-color:#a8c7fa;text-underline-offset:3px"'
    )

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.parts: list[str] = []
        self._stack: list[tuple[str, str]] = []
        self._suppressed_depth = 0

    def _close_from(self, index: int) -> None:
        for _source_tag, output_tag in reversed(self._stack[index:]):
            self.parts.append(f"</{output_tag}>")
        del self._stack[index:]

    def _last_stack_index(
        self, matches: Callable[[tuple[str, str]], bool], *, after: int = -1
    ) -> int:
        """Return the innermost matching open element above ``after``, or -1."""
        return next(
            (
                index
                for index in range(len(self._stack) - 1, after, -1)
                if matches(self._stack[index])
            ),
            -1,
        )

    def _close_open_paragraph(self) -> None:
        matching_index = self._last_stack_index(lambda entry: entry[1] == "p")
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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: C901
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
            list_index = self._last_stack_index(lambda entry: entry[1] in {"ul", "ol"})
            open_item_index = self._last_stack_index(
                lambda entry: entry[1] == "li", after=list_index
            )
            if open_item_index >= 0:
                self._close_from(open_item_index)
            if list_index < 0:
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
        matching_index = self._last_stack_index(lambda entry: entry[0] == tag)
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
        self._close_from(0)
        return "".join(self.parts).strip()


def next_week_start(reference_date: date) -> date:
    """Return the next Monday, treating Monday itself as this week's start."""

    return reference_date + timedelta(days=(7 - reference_date.weekday()) % 7)


def normalize_child_name(value: object) -> str:
    """Return a bounded single-line display name safe for email subjects."""

    if not isinstance(value, str):
        raise TypeError("invalid_child_name")
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
    """Return official age filters that overlap the person's age in a date range."""

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
        if duration_match := pattern.search(description):
            duration = timedelta(minutes=int(duration_match.group("minutes")))
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

    sanitizer = HTMLDescriptionSanitizer(base_url)
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
        value = f"{HTMLDescriptionSanitizer._PARAGRAPH}{value}</p>"
    return value


_VENUE_SUFFIX = (
    r"Park|Square|Playground|Garden|Museum|Community Center|Recreation Center|"
    r"Rec Center|School|Theater|Theatre|Studio|Gallery|Plaza|Courtyard|Field|"
    r"Pool|Market|Pavilion|Campus|Center"
)
_VENUE_NAME = rf"[A-Z][A-Za-z0-9&' .-]{{1,70}}?(?:{_VENUE_SUFFIX})"
_TITLE_VENUE_RE = re.compile(
    # Use the last location lead-in, not language text such as "in Spanish at".
    rf".*\b(?:at|in)\s+(?P<venue>{_VENUE_NAME})\s*[!?.]*$",
    re.IGNORECASE,
)
_DESCRIPTION_VENUE_RES = (
    re.compile(
        rf"\b(?:will take|takes) place at\s+(?P<venue>{_VENUE_NAME})\b",
        re.IGNORECASE,
    ),
    re.compile(rf"\bjoin us in\s+(?P<venue>{_VENUE_NAME})\b", re.IGNORECASE),
    re.compile(
        rf"\b(?:meet us|let['\u2019]s meet) at\s+(?P<venue>{_VENUE_NAME})\b",
        re.IGNORECASE,
    ),
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

    if (match := _TITLE_VENUE_RE.search(title)) and (
        venue := _named_venue(match.group("venue"))
    ):
        return venue
    for pattern in _DESCRIPTION_VENUE_RES:
        for match in pattern.finditer(description):
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
    value = value.removesuffix(suffix)
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
    online = has_positive_claim(_ONLINE_EVENT_RE.pattern, searchable)
    if has_positive_claim(r"\bhybrid\b", searchable) or (
        online and has_positive_claim(_IN_PERSON_EVENT_RE.pattern, searchable)
    ):
        return "hybrid"
    if online:
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
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return ""
    return (
        url
        if parsed.scheme == "https"
        and hostname in TRUSTED_IMAGE_HOSTS
        and port in (None, 443)
        else ""
    )


def parse_feed(
    xml_content: bytes | str,
    branch: Branch,
    age_category: str | None = None,
) -> tuple[list[Event], int]:
    """Parse one official branch RSS feed."""

    root = _safe_feed_root(xml_content)
    items = root.findall("./channel/item")
    events: list[Event] = []
    for item in items[:MAX_PARSED_RSS_ITEMS]:
        start_date_text = (item.findtext("startdate") or "").strip()
        start_time_text = (item.findtext("starttime") or "").strip()
        if not start_date_text or not start_time_text:
            continue
        try:
            event_date = date.strptime(start_date_text, "%m/%d/%y")
            normalized_time = start_time_text.replace(".", "").strip()
            start_time = time.strptime(normalized_time, "%I:%M %p")
        except ValueError:
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


def _safe_feed_root(xml_content: bytes | str) -> ET.Element:
    """Parse a bounded RSS payload after rejecting DTD and entity declarations."""

    security_scan_text = _xml_security_scan_text(xml_content)
    if any(marker in security_scan_text for marker in ("<!doctype", "<!entity")):
        raise ValueError("RSS payload contains a forbidden XML declaration")
    # The fetcher bounds payload size and source hosts. Parse the original content so
    # ElementTree retains its normal XML encoding detection after the normalized scan.
    root = ET.fromstring(xml_content)  # noqa: S314
    if root.tag != "rss" or len(root.findall("channel")) != 1:
        raise ValueError("RSS payload does not contain one feed channel")
    return root


def _xml_security_scan_text(xml_content: bytes | str) -> str:
    """Return an encoding-normalized view for declaration screening."""

    if isinstance(xml_content, str):
        return xml_content.casefold()

    prefix = xml_content[:4]
    if prefix in {b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00"}:
        encoding = "utf-32"
    elif prefix == b"\x00\x00\x00<":
        encoding = "utf-32-be"
    elif prefix == b"<\x00\x00\x00":
        encoding = "utf-32-le"
    elif prefix[:2] in {b"\xfe\xff", b"\xff\xfe"}:
        encoding = "utf-16"
    elif prefix.startswith(b"\x00<\x00"):
        encoding = "utf-16-be"
    elif prefix.startswith(b"<\x00"):
        encoding = "utf-16-le"
    else:
        # ASCII-compatible encodings preserve the declaration tokens byte-for-byte.
        encoding = "latin-1"

    try:
        return xml_content.decode(encoding).casefold()
    except UnicodeDecodeError:
        raise ValueError("RSS payload encoding is invalid") from None


def merge_events(events: Sequence[Event]) -> list[Event]:
    """Deduplicate events with one order-independent effective-row rule."""

    merged: dict[str, Event] = {}
    for event in sorted(events, key=_event_merge_priority):
        key = event_identity(event)
        if existing := merged.get(key):
            age_categories = tuple(
                sorted(
                    {*existing.age_categories, *event.age_categories},
                    key=lambda category: (
                        AGE_CATEGORY_ORDER.get(category, 999),
                        category.casefold(),
                        category,
                    ),
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


def _event_merge_priority(event: Event) -> tuple[bool, int, int, int, int, str]:
    """Return deterministic source precedence for one duplicate occurrence.

    An inactive publisher title wins so a cancellation cannot be hidden by an
    older overlapping feed. Otherwise prefer the row with richer safe source
    content, then use every normalized field as a stable total-order tiebreaker.
    """

    stable_fields = repr(
        (
            event.title,
            event.description,
            event.link,
            event.image_url,
            event.branch,
            tuple(sorted(event.age_categories)),
            event.end_at,
            tuple(
                (link.label, link.url, link.occurrence)
                for link in event.description_links
            ),
            event.description_html,
            event.venue,
            event.room,
            event.modality,
            event.image_layout,
            event.description_truncated,
            event.weather_location_conditional,
        )
    )
    return (
        event_is_active(event),
        -len(event.description),
        -len(event.description_html),
        -int(bool(event.image_url)),
        -int(event.end_at is not None),
        stable_fields,
    )


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


_NEGATED_CLAIM_END_RE = re.compile(
    r"^\s*(?:"
    r"(?:not|no\s+longer|(?:is|are|was|were)\s+(?:not|no\s+longer)|"
    r"(?:isn|aren|wasn|weren)['\u2019]t|"
    r"(?:will (?:not|no\s+longer)|won['\u2019]t|cannot|can['\u2019]t)\s+be|"
    r"(?:has|have)\s+not\s+been|(?:hasn|haven)['\u2019]t\s+been)\s+"
    r"(?:available|provided|required|offered|welcome|included|planned)|"
    r"(?:(?:is|are|was|were|will be|has been|have been)\s+)?unavailable)\b",
    re.IGNORECASE,
)


def has_positive_claim(pattern: str, text: str) -> bool:
    """Match a published highlight unless its own phrase is explicitly negated."""

    for match in re.finditer(pattern, text, re.IGNORECASE):
        before = text[max(0, match.start() - 60) : match.start()]
        after = text[match.end() : match.end() + 60]
        if (
            re.search(
                r"\b(?:no(?:\s+longer)?|not|without|never|cannot|"
                r"(?:isn|aren|wasn|weren|won|can)['\u2019]t)\s+"
                r"(?:(?:an?|any|be|being|have|having|for|offer(?:ing)?|"
                r"provid(?:e|ing))\s+){0,3}$",
                before,
                re.IGNORECASE,
            )
            or re.search(
                r"\b(?:no(?:\s+longer)?|not|without|never|cannot|"
                r"(?:isn|aren|wasn|weren|won|can)['\u2019]t)\b[^.;!?\n]{0,45}"
                r"\b(?:or|nor)\s+(?:an?\s+)?$",
                before,
                re.IGNORECASE,
            )
            or _NEGATED_CLAIM_END_RE.match(after)
        ):
            continue
        return True
    return False
