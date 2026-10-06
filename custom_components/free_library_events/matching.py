"""Age matching and fit classification for Free Library events."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from .model import (
    AGE_CATEGORY_WINDOWS,
    Event,
    FitRank,
    age_in_months,
    event_is_active,
    merge_events,
)

AGE_RANGE_RE = re.compile(
    r"\b(?:(?P<age_context>ages?|aged)|"
    r"children(?:\s+(?P<children_age_context>ages?|aged))?)\s*"
    r"(?P<low>\d{1,3})\s*"
    r"(?P<low_unit>months?|mos?|years?|yrs?)?\s*"
    r"(?:-|\u2013|to|through)\s*(?P<high>\d{1,3})"
    r"(?:\s*(?P<high_unit>months?|mos?|years?|yrs?))?\b",
    re.IGNORECASE,
)
_AGE_RANGE_OR_RE = re.compile(r"[ \t]+(?:old[ \t]+)?or[ \t]+", re.IGNORECASE)
_AGE_RANGE_LIST_END_RE = re.compile(
    r"[ \t]*(?:old\b[ \t]*)?"
    r"(?:(?:(?:are|is)[ \t]+(?:welcome|invited|eligible)"
    r"(?:[ \t]+to[ \t]+(?:attend|join|participate))?|"
    r"(?:can|may)[ \t]+(?:attend|join|participate))[ \t]*)?"
    r"(?=$|[.!?;\n]|\bor\b)",
    re.IGNORECASE,
)
NEWBORN_RANGE_RE = re.compile(
    r"\b(?:children\s+from\s+)?(?:newborns?|birth)\s*"
    r"(?:-|\u2013|to|through)\s*(?:age\s*)?(?P<high>\d{1,3})\s*"
    r"(?P<high_unit>months?|mos?|years?|yrs?)?\b",
    re.IGNORECASE,
)
AGE_AND_UNDER_RE = re.compile(
    r"\b(?:ages?\s*)?(\d{1,3})\s*(months?|mos?|years?|yrs?)?\s+and under\b",
    re.IGNORECASE,
)
UNDER_AGE_RE = re.compile(
    r"\b(?:(?P<context>ages?|children|kids|babies|toddlers|people)\s+)?"
    r"under\s+(?P<age_prefix>age\s+)?(?P<value>\d{1,3})\s*"
    r"(?P<unit>months?|mos?|years?|yrs?)?\b",
    re.IGNORECASE,
)


def _is_month_unit(unit: str | None) -> bool:
    return bool(unit and unit.lower().startswith(("month", "mo")))


def _to_months(value: int, unit: str | None) -> float:
    return float(value) if _is_month_unit(unit) else value * 12.0


def _is_broad_years_only_upper_limit(
    value: int, unit: str | None, child_months: float
) -> bool:
    """Detect upper limits too broad to establish an early-childhood fit."""

    is_years = unit is None or unit.lower().startswith(("year", "yr"))
    return child_months < 36 and is_years and value >= 6


def _has_age_range_evidence(match: re.Match[str]) -> bool:
    return any(
        match.group(field)
        for field in (
            "age_context",
            "children_age_context",
            "low_unit",
            "high_unit",
        )
    )


def _age_range_contains(match: re.Match[str], child_months: float) -> bool:
    low_unit = match.group("low_unit") or match.group("high_unit")
    high_unit = match.group("high_unit") or match.group("low_unit")
    low = _to_months(int(match.group("low")), low_unit)
    high = _to_months(int(match.group("high")), high_unit)
    margin = 1 if _is_month_unit(high_unit) else 12
    return low <= child_months < high + margin


def _explicit_age_fit(text: str, child_months: float) -> FitRank | None:  # noqa: C901
    match = NEWBORN_RANGE_RE.search(text)
    if match:
        high_unit = match.group("high_unit")
        high = _to_months(int(match.group("high")), high_unit)
        margin = 1 if _is_month_unit(high_unit) else 12
        return "best" if child_months < high + margin else "exclude"

    for match in AGE_RANGE_RE.finditer(text):
        if not _has_age_range_evidence(match):
            continue
        if _age_range_contains(match, child_months):
            return "best"
        # Only an immediate, explicit alternative can extend this audience.
        # Other prose, role labels, and session/time qualifiers keep the first
        # range authoritative rather than combining unrelated ages.
        current_range = match
        while connector := _AGE_RANGE_OR_RE.match(text, current_range.end()):
            alternative = AGE_RANGE_RE.match(text, connector.end())
            if (
                alternative is None
                or not _has_age_range_evidence(alternative)
                or not _AGE_RANGE_LIST_END_RE.match(text, alternative.end())
            ):
                break
            if _age_range_contains(alternative, child_months):
                return "best"
            current_range = alternative
        return "exclude"

    match = AGE_AND_UNDER_RE.search(text)
    if match:
        upper_value = int(match.group(1))
        upper_unit = match.group(2)
        upper = _to_months(upper_value, upper_unit)
        margin = 1 if _is_month_unit(upper_unit) else 12
        if child_months < upper + margin:
            if _is_broad_years_only_upper_limit(upper_value, upper_unit, child_months):
                return "broad"
            return "best"
        return "exclude"

    for match in UNDER_AGE_RE.finditer(text):
        upper_unit = match.group("unit")
        if not (upper_unit or match.group("context") or match.group("age_prefix")):
            continue
        upper_value = int(match.group("value"))
        upper = _to_months(upper_value, upper_unit)
        if child_months < upper:
            if _is_broad_years_only_upper_limit(upper_value, upper_unit, child_months):
                return "broad"
            return "best"
        return "exclude"
    return None


_BABY_TERM = r"(?:bab(?:y|ies)|infants?)"
_BABY_AUDIENCE_CONTINUATION = (
    r"(?=\s*(?:$|[.,;:!?)]|(?:and|or|with|who|to|from|under|up to|ages?|aged|"
    r"can|may|will|enjoys?|loves?|explores?|learns?|plays?)\b))"
)
_BABY_PROGRAM = (
    r"(?:story[ -]?(?:time|hour)|music|play(?:time|group)|rhymes?|bounce|yoga|"
    r"massage|sign(?:ing| language)|program|event|session|class|stories|songs|activities)"
)
_BABY_AUDIENCE_SUBJECT = (
    rf"(?:(?:your\s+)?{_BABY_TERM}(?:\s*(?:&|and|with|/)\s*"
    r"(?:(?:their|a)\s+)?(?:caregivers?|parents?|toddlers?))?"
    rf"|(?:caregivers?|parents?|toddlers?)\s*(?:&|and|with|/)\s*{_BABY_TERM})"
)
_BABY_AUDIENCE_RE = re.compile(
    # Anchor age inference to a program, eligibility statement or invitation.
    # Topic phrases such as "care for babies" or "their infants" are not enough.
    rf"\b{_BABY_TERM}(?:\s*(?:&|and|/)\s*toddlers?)?[ -]+{_BABY_PROGRAM}\b"
    r"|\b(?:baby\s*(?:&|and)\s*me|read,?\s+baby,?\s+read|lap[ -]sit)\b"
    rf"|(?:^|[.!?]\s+)(?:(?:(?:this|the|a|our)\s+)?{_BABY_PROGRAM}"
    rf"(?:\s+(?:(?:and|&)\s+)?{_BABY_PROGRAM})*\s+(?:(?:is|are)\s+)?)?"
    r"(?:(?:designed|intended|suitable|appropriate|recommended|perfect)\s+)?"
    rf"for\s+{_BABY_TERM}{_BABY_AUDIENCE_CONTINUATION}"
    rf"|(?:^|[.!?]\s+){_BABY_AUDIENCE_SUBJECT}\s+"
    r"(?:(?:(?:are|is)\s+)?welcome|(?:can|may)\s+(?:attend|join|participate|enjoy))\b"
    rf"|(?:^|[.!?]\s+)(?:bring|join us with)\s+(?:your\s+)?{_BABY_TERM}"
    rf"{_BABY_AUDIENCE_CONTINUATION}",
    re.MULTILINE,
)
_TODDLER_AUDIENCE_RE = re.compile(r"\b(?:toddlers?|twos)\b")
_PRESCHOOL_AUDIENCE_RE = re.compile(r"\bpre-?school(?:ers?)?\b")
_SCHOOL_AGE_AUDIENCE_RE = re.compile(r"\bschool[ -]aged?\b")
_TEEN_AUDIENCE_RE = re.compile(r"\bteen(?:s|age(?:rs?)?)?\b")
_ADULT_AUDIENCE_RE = re.compile(r"\badults?\b")


def classify_event(event: Event, birth_date: date) -> FitRank:  # noqa: C901
    """Classify an event using only deterministic published-text rules."""

    if event.event_date < birth_date:
        return "exclude"
    text = f"{event.title} {event.description}".lower()
    child_months = age_in_months(birth_date, event.event_date)
    explicit = _explicit_age_fit(text, child_months)
    if explicit is not None:
        return explicit

    if any(
        category in event.age_categories and minimum <= child_months < maximum
        for category, minimum, maximum in AGE_CATEGORY_WINDOWS
    ):
        return "best"

    baby_audience = bool(
        _BABY_AUDIENCE_RE.search(f"{event.title}\n{event.description}".lower())
    )
    toddler_audience = bool(_TODDLER_AUDIENCE_RE.search(text))
    preschool_audience = bool(_PRESCHOOL_AUDIENCE_RE.search(text))
    school_age_audience = bool(_SCHOOL_AGE_AUDIENCE_RE.search(text))
    teen_audience = bool(_TEEN_AUDIENCE_RE.search(text))
    adult_audience = bool(_ADULT_AUDIENCE_RE.search(text))

    if child_months < 36 and baby_audience:
        return "best"
    if 9 <= child_months < 48 and toddler_audience:
        return "best"
    if 30 <= child_months < 72 and preschool_audience:
        return "best"
    if 60 <= child_months < 156 and school_age_audience:
        return "best"
    if 144 <= child_months < 228 and teen_audience:
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

    if any(
        (
            baby_audience,
            toddler_audience,
            preschool_audience,
            school_age_audience,
            teen_audience,
            adult_audience,
        )
    ):
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

    relevant_events = [
        event
        for event in merge_events(events)
        if start_date <= event.event_date <= end_date and event_is_active(event)
    ]

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
