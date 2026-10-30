"""Synthetic publisher responses shared by the Home Assistant tests."""

from __future__ import annotations

from custom_components.free_library_events.api import BranchFeed


def empty_feed(age_category: str | None) -> BranchFeed:
    """Return a complete empty publisher response for the requested age feed."""

    return BranchFeed(
        events=(),
        age_category=age_category,
        source_count=0,
        parsed_count=0,
        last_event_date=None,
        ordered=True,
    )
