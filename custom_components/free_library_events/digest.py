"""Build deterministic Free Library email digests from parsed events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Literal

from .email_render import (
    MIDDLE_DOT,
    bounded_text,
    event_chip_specs,
    event_location_note,
    google_calendar_url,
    render_event_card,
    render_html,
    render_plain_text,
    subject_week_range,
)
from .matching import matching_events
from .model import (
    FILTER_MODES,
    Branch,
    Event,
    event_identity,
    event_is_active,
    merge_events,
    next_week_start,
    normalize_child_name,
)

MAX_CARD_DESCRIPTION_CHARS = 1_800
MAX_DIGEST_HTML_BYTES = 80_000
MAX_EMAIL_EVENTS = 100


def select_digest_events(
    events: Sequence[Event],
    *,
    birth_date: date,
    filter_mode: str,
    week_start: date,
    week_end: date,
) -> tuple[list[Event], list[Event]]:
    """Return active weekly occurrences and the age-matched subset."""

    weekly_events = [
        event
        for event in merge_events(events)
        if week_start <= event.event_date <= week_end and event_is_active(event)
    ]
    return weekly_events, matching_events(
        weekly_events,
        birth_date,
        filter_mode,
        week_start,
        week_end,
    )


def _display_event(event: Event) -> Event:
    """Return an email-bounded event while preserving source data upstream."""

    description = bounded_text(event.description, MAX_CARD_DESCRIPTION_CHARS)
    truncated = description != " ".join(event.description.split())
    return replace(
        event,
        description=description,
        description_html="" if truncated else event.description_html,
        description_truncated=truncated,
        weather_location_conditional=bool(event_location_note(event)),
        display_highlights=event_chip_specs(event),
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
    # The caller caps candidates at MAX_EMAIL_EVENTS. Keep both representations
    # only for this invocation, keyed by the complete displayed event (including
    # image/CID overrides), rather than its source identity alone.
    rendered_cards = {
        (event, compact): render_event_card(
            event, duration_minutes=duration_minutes, compact=compact
        )
        for event in rendered_events
        for compact in (False, True)
    }
    # URL eligibility is stable for this invocation. Reuse it when trying smaller
    # event sets instead of rebuilding each URL for every footer and preheader.
    calendar_link_ids = frozenset(
        event_identity(event)
        for event in rendered_events
        if google_calendar_url(event, duration_minutes, compact=True)
    )

    def render(full_ids: frozenset[str]) -> str:
        return render_html(
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
            rendered_cards=rendered_cards,
            calendar_link_ids=calendar_link_ids,
        )

    def full_card_delta(event: Event) -> int:
        return len(rendered_cards[(event, False)].encode("utf-8")) - len(
            rendered_cards[(event, True)].encode("utf-8")
        )

    compact_html = render(frozenset())
    while len(compact_html.encode("utf-8")) > MAX_DIGEST_HTML_BYTES and rendered_events:
        removed = priority.pop()
        rendered_events.remove(removed)
        omitted_count += 1
        compact_html = render(frozenset())

    html_bytes = len(compact_html.encode("utf-8"))
    if priority:
        nearest_delta = full_card_delta(priority[0])
        while len(priority) > 1 and html_bytes + nearest_delta > MAX_DIGEST_HTML_BYTES:
            removed = priority.pop()
            rendered_events.remove(removed)
            omitted_count += 1
            compact_html = render(frozenset())
            html_bytes = len(compact_html.encode("utf-8"))

    full_ids: set[str] = set()
    for event in priority:
        identity = event_identity(event)
        delta = full_card_delta(event)
        if html_bytes + delta <= MAX_DIGEST_HTML_BYTES:
            full_ids.add(identity)
            html_bytes += delta

    frozen_ids = frozenset(full_ids)
    rendered = render(frozen_ids)
    # Card deltas cannot account for every shared header change (for example,
    # adding the first photo). Enforce the contract on the final representation.
    while full_ids and len(rendered.encode("utf-8")) > MAX_DIGEST_HTML_BYTES:
        farthest_full = next(
            event_identity(event)
            for event in reversed(priority)
            if event_identity(event) in full_ids
        )
        full_ids.remove(farthest_full)
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
        raise ValueError("Choose at least one library branch.")
    if filter_mode not in FILTER_MODES:
        raise ValueError(f"Choose a filter mode from: {', '.join(FILTER_MODES)}")
    if not 15 <= duration_minutes <= 240:
        raise ValueError("Enter a calendar duration from 15 to 240 minutes.")

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
        f"for {child_name} \U0001f4da {MIDDLE_DOT} "
        f"{subject_week_range(week_start, week_end)}"
    )
    return {
        "subject": subject,
        "message": render_plain_text(
            email_events,
            child_name=child_name,
            birth_date=birth_date,
            week_start=week_start,
            week_end=week_end,
            branches=selected_branches,
            duration_minutes=duration_minutes,
            source_errors=source_errors,
            source_warnings=source_warnings,
            email_omitted_count=email_omitted_count,
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
            "included_occurrence_ids": [
                event_identity(event) for event in source_included
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
