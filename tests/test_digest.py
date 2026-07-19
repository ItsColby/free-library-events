from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "custom_components" / "free_library_events" / "digest.py"
SPEC = importlib.util.spec_from_file_location("free_library_events_digest", SCRIPT)
assert SPEC and SPEC.loader
digest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = digest
SPEC.loader.exec_module(digest)


def rss(items: list[dict[str, str]]) -> str:
    rows = []
    for item in items:
        rows.append(
            "<item>"
            f"<title>{item['title']}</title>"
            f"<description><![CDATA[<p>{item['description']}</p> {item['date']}, {item['time']} - {item['branch']}]]></description>"
            f"<link>{item['link']}</link>"
            f"<guid>{item['link']}</guid>"
            f"<startdate>{item['date']}</startdate>"
            f"<starttime>{item['time']}</starttime>"
            f"<eventimage>{item.get('image_url', '')}</eventimage>"
            "</item>"
        )
    return "<?xml version='1.0'?><rss><channel>" + "".join(rows) + "</channel></rss>"


class DigestTests(unittest.TestCase):
    def test_supported_branch_metadata_uses_official_sources(self) -> None:
        parkway = digest.BRANCHES["CEN"]
        self.assertEqual(parkway.name, "Parkway Central Library")
        self.assertEqual(
            parkway.address,
            "1901 Vine Street, Philadelphia, PA 19103-1189",
        )
        self.assertIn("location=CEN", parkway.rss_url)
        self.assertIn("location_code=CEN", parkway.calendar_url)

        pci = digest.BRANCHES["PCI"]
        self.assertEqual(pci.name, "Philadelphia City Institute")
        self.assertEqual(
            pci.address,
            "1905 Locust Street, Philadelphia, PA 19103-5730",
        )
        self.assertIn("location=PCI", pci.rss_url)
        self.assertIn("location_code=PCI", pci.calendar_url)

    def test_custom_feed_combines_branch_with_singular_age_parameter(self) -> None:
        url = digest.BRANCHES["CEN"].rss_url_for_age("Baby")

        self.assertIn("location=CEN", url)
        self.assertIn("age=Baby", url)
        self.assertNotIn("ages=", url)

        expanded_url = digest.BRANCHES["CEN"].rss_url_for_age_and_type(
            "Young Adult", "Family Programs"
        )
        self.assertIn("location=CEN", expanded_url)
        self.assertIn("age=Young+Adult", expanded_url)
        self.assertIn("type=Family+Programs", expanded_url)
        self.assertNotIn("types=", expanded_url)

    def test_age_source_plan_includes_overlapping_official_categories(self) -> None:
        self.assertEqual(
            digest.age_categories_for_window(
                date(2025, 1, 15),
                date(2026, 7, 20),
                date(2026, 7, 26),
            ),
            ("Baby", "Toddler"),
        )

    def test_age_source_plan_advances_across_the_full_life_cycle(self) -> None:
        cases = (
            (date(2026, 7, 18), ("Baby",)),
            (date(2022, 7, 18), ("Preschool",)),
            (date(2016, 7, 18), ("School Age",)),
            (date(2011, 7, 18), ("Young Adult",)),
            (date(1996, 7, 18), ("Adult",)),
            (date(1956, 7, 18), ("Adult", "Senior")),
        )

        for birth_date, expected in cases:
            with self.subTest(birth_date=birth_date):
                self.assertEqual(
                    digest.age_categories_for_window(
                        birth_date,
                        date(2026, 7, 18),
                        date(2026, 7, 18),
                    ),
                    expected,
                )

    def test_source_plan_uses_complete_life_stage_provenance(self) -> None:
        self.assertEqual(
            digest.source_age_categories_for_window(
                date(2025, 11, 7),
                date(2026, 7, 18),
                date(2026, 10, 16),
            ),
            ("Baby", "Toddler", "Preschool", "School Age", "Young Adult"),
        )
        self.assertEqual(
            digest.source_age_categories_for_window(
                date(1996, 7, 18),
                date(2026, 7, 18),
                date(2026, 10, 16),
            ),
            ("Adult", "Senior"),
        )
        self.assertEqual(
            digest.source_age_categories_for_window(
                date(2008, 8, 15),
                date(2026, 6, 1),
                date(2026, 9, 1),
            ),
            tuple(digest.AGE_CATEGORY_ORDER),
        )

    def test_official_age_category_precedes_title_only_inference(self) -> None:
        event = digest.Event(
            title="Preschool Storytime",
            event_date=date(2026, 7, 24),
            start_time=digest.time(10, 30),
            description="Stories, songs, and movement with caregivers.",
            link="https://example.test/events/structured-age",
            image_url="",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Toddler",),
        )

        self.assertEqual(
            digest.classify_event(event, date(2025, 1, 15)),
            "best",
        )

    def test_explicit_inclusive_text_can_override_a_nonmatching_feed_category(
        self,
    ) -> None:
        cases = (
            (
                "Music with Ry",
                "A music program designed to get even the smallest kiddo clapping.",
                ("Toddler",),
                "good",
            ),
            (
                "Crafternoon for Kids",
                "Kids of all ages are welcome. Even the littlest littles can color.",
                ("School Age",),
                "good",
            ),
            (
                "Library Playgroup",
                "Toys good for a range of ages are available.",
                ("Toddler", "Preschool", "School Age"),
                "possible",
            ),
            (
                "Family Storytime with AAC",
                "An inclusive storytime where all children can communicate and take part.",
                ("Toddler",),
                "good",
            ),
        )

        for title, description, age_categories, expected in cases:
            with self.subTest(title=title):
                event = digest.Event(
                    title=title,
                    event_date=date(2026, 7, 24),
                    start_time=digest.time(10, 0),
                    description=description,
                    link=f"https://example.test/{title}",
                    image_url="",
                    branch=digest.BRANCHES["SWK"],
                    age_categories=age_categories,
                )
                self.assertEqual(
                    digest.classify_event(event, date(2025, 11, 7)),
                    expected,
                )

    def test_nonmatching_feed_category_still_rejects_generic_family_copy(
        self,
    ) -> None:
        event = digest.Event(
            title="Family Art Workshop",
            event_date=date(2026, 7, 24),
            start_time=digest.time(10, 0),
            description="Families can make art together.",
            link="https://example.test/family-art",
            image_url="",
            branch=digest.BRANCHES["SWK"],
            age_categories=("School Age",),
        )

        self.assertEqual(
            digest.classify_event(event, date(2025, 11, 7)),
            "exclude",
        )

    def test_merge_events_preserves_all_official_age_categories(self) -> None:
        base = digest.Event(
            title="Baby & Toddler Storytime!",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10, 30),
            description="Stories and songs with caregivers.",
            link="https://example.test/events/shared",
            image_url="",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby",),
        )
        toddler = digest.replace(base, age_categories=("Toddler",))

        self.assertEqual(
            digest.merge_events((base, toddler))[0].age_categories,
            ("Baby", "Toddler"),
        )

    def test_merge_events_retains_richer_safe_source_fields(self) -> None:
        base = digest.Event(
            title="Baby Storytime",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10, 30),
            description="Stories for babies.",
            link="https://example.test/events/shared",
            image_url="",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby",),
        )
        richer = digest.replace(
            base,
            image_url="https://example.test/event.jpg",
            age_categories=("Toddler",),
            end_at=digest.datetime(2026, 7, 20, 11, 30),
            description_links=(
                digest.DescriptionLink("Resource", "https://example.test/resource"),
            ),
            venue="Sister Cities Park",
            room="Storyhour Room",
        )

        merged = digest.merge_events((base, richer))[0]

        self.assertEqual(merged.image_url, richer.image_url)
        self.assertEqual(merged.end_at, richer.end_at)
        self.assertEqual(merged.description_links, richer.description_links)
        self.assertEqual(merged.venue, richer.venue)
        self.assertEqual(merged.room, richer.room)

        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 10, 7),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["CEN"]],
            reference_date=date(2026, 7, 18),
            events=(base, richer),
            source_counts={"Parkway Central Library": 2},
        )
        self.assertEqual(payload["metadata"]["scanned_count"], 1)
        self.assertIn("Storyhour Room", payload["html"])
        self.assertIn(richer.image_url, payload["html"])

    def test_next_week_start_treats_monday_as_current_week(self) -> None:
        self.assertEqual(digest.next_week_start(date(2026, 7, 20)), date(2026, 7, 20))
        self.assertEqual(digest.next_week_start(date(2026, 7, 17)), date(2026, 7, 20))

    def test_feed_title_repairs_library_ampersand_loss(self) -> None:
        self.assertEqual(
            digest.clean_title(
                "07/20/26: Baby  Toddler Storytime! - Parkway Central Library",
                digest.BRANCHES["CEN"],
            ),
            "Baby & Toddler Storytime!",
        )

    def test_parser_skips_one_malformed_item_without_losing_the_feed(self) -> None:
        items = [
            {
                "title": "Bad date",
                "description": "This row should be skipped.",
                "date": "not-a-date",
                "time": "10:00 A.M.",
                "branch": "Charles Santore Library",
                "link": "https://example.test/bad",
            },
            {
                "title": "07/22/26: Baby Music - Charles Santore Library",
                "description": "A music program for babies and caregivers.",
                "date": "07/22/26",
                "time": "10:30 A.M.",
                "branch": "Charles Santore Library",
                "link": "https://example.test/good",
            },
        ]

        events, source_count = digest.parse_feed(
            rss(items), digest.BRANCHES["SWK"], "Baby"
        )

        self.assertEqual(source_count, 2)
        self.assertEqual(
            [event.link for event in events], ["https://example.test/good"]
        )
        self.assertEqual(events[0].age_categories, ("Baby",))

    def test_parser_suppresses_empty_image_filenames(self) -> None:
        item = {
            "title": "07/25/26: Family Storytime - Charles Santore Library",
            "description": "An inclusive storytime where all children can take part.",
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "https://example.test/events/171403",
            "image_url": (
                "https://libwww.freelibrary.org/assets/images/calendar/"
                "events/2026/11/.jpg"
            ),
        }

        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )

        self.assertEqual(events[0].image_url, "")

        item["image_url"] = (
            "https://libwww.freelibrary.org/assets/images/calendar/"
            "events/2026/11/171403.jpg"
        )
        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )
        self.assertEqual(events[0].image_url, item["image_url"])

    def test_parser_rejects_non_http_event_and_image_urls(self) -> None:
        item = {
            "title": "07/25/26: Family Storytime - Charles Santore Library",
            "description": "An inclusive storytime where all children can take part.",
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "javascript:alert(1)",
            "image_url": "data:image/svg+xml,unsafe",
        }

        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )

        self.assertEqual(events[0].link, "")
        self.assertEqual(events[0].image_url, "")

        payload = rss([item]).replace(
            "<guid>javascript:alert(1)</guid>",
            "<guid>https://example.test/fallback-event</guid>",
        )
        events, _source_count = digest.parse_feed(
            payload, digest.BRANCHES["SWK"], "Toddler"
        )
        self.assertEqual(events[0].link, "https://example.test/fallback-event")

    def test_parser_resolves_safe_relative_source_urls(self) -> None:
        item = {
            "title": "07/25/26: Family Storytime - Charles Santore Library",
            "description": 'Read the <a href="/programs/literacy">literacy guide</a>.',
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "",
            "image_url": "/assets/images/event.jpg",
        }

        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )

        self.assertEqual(
            events[0].image_url,
            "https://libwww.freelibrary.org/assets/images/event.jpg",
        )
        self.assertEqual(
            events[0].description_links[0].url,
            "https://libwww.freelibrary.org/programs/literacy",
        )
        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 10, 7),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["SWK"]],
            reference_date=date(2026, 7, 18),
            events=events,
            source_counts={"Charles Santore Library": 1},
        )
        self.assertIn(
            f"Event details: {digest.BRANCHES['SWK'].calendar_url}",
            payload["message"],
        )

    def test_parser_preserves_safe_description_links_and_explicit_room(self) -> None:
        item = {
            "title": "07/25/26: Family Storytime with AAC - Charles Santore Library",
            "description": (
                'Learn about <a href="https://www.asha.org/public/speech/disorders/aac/">'
                "Augmentative and Alternative Communication (AAC)</a>. "
                'Ignore <a href="javascript:alert(1)">this unsafe link</a>. '
                "We will be meeting in the Storyhour Room."
            ),
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "https://libwww.freelibrary.org/calendar/event/171403",
        }

        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )
        event = events[0]

        self.assertEqual(event.room, "Storyhour Room")
        self.assertEqual(
            event.description_links,
            (
                digest.DescriptionLink(
                    "Augmentative and Alternative Communication (AAC)",
                    "https://www.asha.org/public/speech/disorders/aac/",
                ),
            ),
        )
        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 10, 7),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["SWK"]],
            reference_date=date(2026, 7, 18),
            events=events,
            source_counts={"Charles Santore Library": 1},
        )
        self.assertIn(
            'href="https://www.asha.org/public/speech/disorders/aac/"', payload["html"]
        )
        self.assertNotIn("javascript:", payload["html"])
        self.assertIn("Storyhour Room", payload["html"])
        self.assertIn(
            "Related: Augmentative and Alternative Communication (AAC): "
            "https://www.asha.org/public/speech/disorders/aac/",
            payload["message"],
        )

        self.assertEqual(
            digest.explicit_room("The Storyhour Room is on the first floor."),
            "Storyhour Room",
        )
        self.assertEqual(
            digest.explicit_room("Meet on the ground floor in Room 22."),
            "Room 22",
        )
        self.assertEqual(digest.explicit_room("Meet in the meeting room."), "")
        self.assertEqual(
            digest.explicit_room("8/3: Meeting Room\n8/10: Family craft night"),
            "",
        )

    def test_explicit_offsite_venue_replaces_branch_map_destination(self) -> None:
        cases = (
            (
                "Storytime at Sister Cities Park!",
                "This outdoor storytime will take place at Sister Cities Park.",
                "Sister Cities Park",
            ),
            (
                "Read, Baby, Read Storytime",
                "Join us in Rittenhouse Square by the Goat Statue for this program!",
                "Rittenhouse Square",
            ),
        )
        for title, description, expected in cases:
            with self.subTest(title=title):
                event = digest.Event(
                    title=title,
                    event_date=date(2026, 7, 22),
                    start_time=digest.time(10, 30),
                    description=description,
                    link="https://example.test/event",
                    image_url="",
                    branch=digest.BRANCHES["CEN"],
                    age_categories=("Baby",),
                    venue=digest.explicit_venue(title, description),
                )
                self.assertEqual(event.venue, expected)
                self.assertEqual(digest.event_location_name(event), expected)
                self.assertIn(
                    digest.urllib.parse.quote_plus(expected),
                    digest.event_directions_url(event),
                )
                self.assertNotIn(
                    digest.urllib.parse.quote_plus(digest.BRANCHES["CEN"].name),
                    digest.event_directions_url(event),
                )

        self.assertEqual(
            digest.explicit_venue(
                "Storytime in the park", "Join us in the park for stories."
            ),
            "",
        )
        self.assertEqual(
            digest.explicit_venue("Storytime at The Park", "Join us in The Park."),
            "",
        )

    def test_age_on_event_date(self) -> None:
        self.assertEqual(digest.age_on(date(2025, 1, 15), date(2026, 7, 24)), (1, 6, 9))
        self.assertEqual(
            digest.format_age(date(2025, 1, 15), date(2026, 7, 24)),
            "18 months",
        )

    def test_age_display_uses_conversational_units(self) -> None:
        self.assertEqual(
            digest.format_age(date(2026, 7, 1), date(2026, 7, 18)), "2 weeks"
        )
        self.assertEqual(
            digest.format_age(date(2026, 5, 18), date(2026, 7, 18)), "2 months"
        )
        self.assertEqual(
            digest.format_age(date(2026, 1, 15), date(2026, 7, 18)), "6 months"
        )
        self.assertEqual(
            digest.format_age(date(2024, 1, 15), date(2026, 7, 18)), "2½ years"
        )
        self.assertEqual(
            digest.format_age(date(2023, 9, 15), date(2026, 7, 18)), "2 years"
        )
        self.assertEqual(
            digest.format_age(date(2021, 1, 15), date(2026, 7, 18)), "5 years"
        )

    def test_explicit_end_evidence_must_be_confident(self) -> None:
        self.assertEqual(
            digest.explicit_end_at(
                date(2026, 7, 20),
                digest.time(10, 30),
                "Storytime runs from 10:30 a.m. to 11:30 a.m.",
            ),
            digest.datetime(2026, 7, 20, 11, 30),
        )
        self.assertIsNone(
            digest.explicit_end_at(
                date(2026, 7, 20),
                digest.time(10, 30),
                "Playtime runs from 12:00 p.m. to 1:00 p.m.",
            )
        )
        self.assertEqual(
            digest.explicit_end_at(
                date(2026, 7, 20),
                digest.time(11, 30),
                "The program runs from 11:30 to 1:00 p.m.",
            ),
            digest.datetime(2026, 7, 20, 13, 0),
        )
        self.assertEqual(
            digest.explicit_end_at(
                date(2026, 7, 20),
                digest.time(10, 30),
                "Each 90-minute class is free.",
            ),
            digest.datetime(2026, 7, 20, 12, 0),
        )
        self.assertIsNone(
            digest.explicit_end_at(
                date(2026, 7, 20),
                digest.time(10, 30),
                "The event includes a 10-minute welcome and open-ended playtime.",
            )
        )

    def test_description_link_replaces_its_published_occurrence(self) -> None:
        item = {
            "title": "07/25/26: Family Storytime - Charles Santore Library",
            "description": (
                "The literacy guide is useful. Read the "
                '<a href="https://example.test/guide">literacy guide</a>.'
            ),
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "https://example.test/event",
        }
        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )

        rendered = digest._description_html(events[0])

        self.assertTrue(rendered.startswith("The literacy guide is useful."))
        self.assertEqual(rendered.count("<a "), 1)
        self.assertIn(">literacy guide</a>.", rendered)

    def test_explicit_age_range_overrides_all_ages_wording(self) -> None:
        event = digest.Event(
            title="Writing Workshop",
            event_date=date(2026, 7, 21),
            start_time=digest.time(13, 0),
            description="Perfect for aspiring writers ages 8 to 12. Anyone is welcome.",
            link="https://example.test/1",
            image_url="",
            branch=digest.BRANCHES["IND"],
        )
        self.assertEqual(digest.classify_event(event, date(2025, 1, 15)), "exclude")

    def test_broad_upper_age_limit_is_not_a_recommended_toddler_match(self) -> None:
        event = digest.Event(
            title="Chess Club for Kids",
            event_date=date(2026, 7, 20),
            start_time=digest.time(16, 0),
            description="Kids 12 and under are welcome to play and learn.",
            link="https://example.test/chess",
            image_url="",
            branch=digest.BRANCHES["CEN"],
        )
        fit = digest.classify_event(event, date(2025, 1, 15))
        self.assertEqual(fit, "broad")
        self.assertFalse(digest.include_fit(fit, "Recommended"))

        event = digest.replace(
            event,
            title="Baby Storytime",
            description="Intended for ages 2 and under and their caregivers.",
        )
        self.assertEqual(digest.classify_event(event, date(2025, 1, 15)), "best")

    def test_recommended_matching_is_deterministic(self) -> None:
        cases = [
            ("Baby Storytime", "For babies and toddlers with caregivers.", "best"),
            (
                "Crafternoon",
                "Kids of all ages are welcome, including the littlest littles.",
                "good",
            ),
            ("Playgroup", "Toys are available for a range of ages.", "possible"),
            ("Chair Yoga", "Suitable for all levels and ages.", "exclude"),
        ]
        for title, description, expected in cases:
            with self.subTest(title=title):
                event = digest.Event(
                    title=title,
                    event_date=date(2026, 7, 24),
                    start_time=digest.time(10, 0),
                    description=description,
                    link=f"https://example.test/{title}",
                    image_url="",
                    branch=digest.BRANCHES["SWK"],
                )
                self.assertEqual(
                    digest.classify_event(event, date(2025, 1, 15)),
                    expected,
                )

    def test_inactive_events_are_not_returned(self) -> None:
        event = digest.Event(
            title="Art Workshop: POSTPONED to July 27",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10, 0),
            description="For babies and toddlers with caregivers.",
            link="https://example.test/postponed",
            image_url="",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby",),
        )

        self.assertFalse(digest.event_is_active(event))
        self.assertEqual(
            digest.matching_events(
                [event],
                date(2025, 11, 7),
                "Recommended",
                date(2026, 7, 20),
                date(2026, 7, 26),
            ),
            [],
        )

        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 11, 7),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["CEN"]],
            reference_date=date(2026, 7, 18),
            events=[event],
            source_counts={"Parkway Central Library": 1},
        )
        self.assertEqual(payload["metadata"]["scanned_count"], 0)
        self.assertEqual(payload["metadata"]["omitted_count"], 0)
        self.assertNotIn(event.title, payload["message"])
        self.assertNotIn(event.title, payload["html"])

    def test_digest_output_contains_google_links_and_expected_ids(self) -> None:
        fixture_items = {
            "SWK": [
                {
                    "title": "07/22/26: Baby Music - Charles Santore Library",
                    "description": "A music program for babies and caregivers.",
                    "date": "07/22/26",
                    "time": "10:30 A.M.",
                    "branch": "Charles Santore Library",
                    "link": "https://example.test/events/1001",
                },
                {
                    "title": "07/20/26: Teen Games - Charles Santore Library",
                    "description": "Open to all individuals ages 12 to 18.",
                    "date": "07/20/26",
                    "time": "4:00 P.M.",
                    "branch": "Charles Santore Library",
                    "link": "https://example.test/events/1002",
                },
            ],
            "IND": [
                {
                    "title": "07/24/26: Baby Storytime  Playgroup - Independence Library",
                    "description": "Stories and songs for babies and toddlers with caregivers.",
                    "date": "07/24/26",
                    "time": "10:30 A.M.",
                    "branch": "Independence Library",
                    "link": "https://example.test/events/1003",
                }
            ],
            "CEN": [
                {
                    "title": "07/22/26: Family Storytime - Parkway Central Library",
                    "description": "Stories and songs for babies and caregivers.",
                    "date": "07/22/26",
                    "time": "11:00 A.M.",
                    "branch": "Parkway Central Library",
                    "link": "https://example.test/events/1004",
                }
            ],
            "PCI": [
                {
                    "title": "07/23/26: Toddler Art Studio - Philadelphia City Institute",
                    "description": "Process art for toddlers and caregivers.",
                    "date": "07/23/26",
                    "time": "11:15 A.M.",
                    "branch": "Philadelphia City Institute",
                    "link": "https://example.test/events/1005",
                }
            ],
        }
        events = []
        source_counts = {}
        for code, items in fixture_items.items():
            parsed, source_counts[code] = digest.parse_feed(
                rss(items), digest.BRANCHES[code]
            )
            events.extend(parsed)

        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 1, 15),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=list(digest.BRANCHES.values()),
            reference_date=date(2026, 7, 17),
            events=events,
            source_counts=source_counts,
        )

        self.assertEqual(payload["metadata"]["included_count"], 4)
        self.assertEqual(payload["metadata"]["omitted_count"], 1)
        self.assertEqual(
            payload["metadata"]["included_event_ids"],
            ["1001", "1004", "1005", "1003"],
        )
        self.assertIn("calendar.google.com/calendar/render", payload["html"])
        self.assertIn("Avery, who is 18 months old", payload["html"])
        self.assertNotIn("Avery will be", payload["html"])
        self.assertNotIn("No registration information listed", payload["html"])
        self.assertNotIn("No cost information listed", payload["html"])
        self.assertNotIn("Not listed by the library", payload["html"])
        self.assertNotIn("18 South 7th Street", payload["html"])
        self.assertNotIn("215-685-1633", payload["html"])
        self.assertIn(
            'href="https://example.test/events/1003"',
            payload["html"],
        )
        self.assertIn(
            "https://www.google.com/maps/search/?api=1&amp;query=Independence+Library",
            payload["html"],
        )
        self.assertNotIn('href="tel:', payload["html"])
        self.assertNotIn("1905 Locust Street", payload["html"])
        self.assertNotIn(">Directions</a>", payload["html"])
        self.assertNotIn(">Event details</a>", payload["html"])
        self.assertNotIn("Prepared automatically by Home Assistant", payload["html"])
        self.assertEqual(payload["metadata"]["scanned_count"], 5)
        self.assertIn("<h2", payload["html"])
        self.assertIn("<h3", payload["html"])
        self.assertEqual(payload["html"].count("Wednesday, July 22"), 1)
        self.assertEqual(payload["message"].count("WEDNESDAY, JULY 22"), 1)
        self.assertIn("text-decoration:underline", payload["html"])

    def test_source_coverage_and_errors_are_disclosed_in_both_bodies(self) -> None:
        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 1, 15),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=list(digest.BRANCHES.values()),
            reference_date=date(2026, 7, 17),
            events=[],
            source_counts={"Philadelphia City Institute": 10},
            source_errors=["Parkway Central Library"],
            source_warnings=[
                "Philadelphia City Institute — Toddler reached its 10-item limit"
            ],
            supplemental_age_failures=[
                "Parkway Central Library — Young Adult could not be loaded"
            ],
            supplemental_age_limitations=[
                "Charles Santore Library — School Age reached its 10-item limit"
            ],
        )

        for body in (payload["message"], payload["html"]):
            self.assertIn(
                "Philadelphia City Institute — Toddler reached its 10-item limit",
                body,
            )
            self.assertIn("could not load: Parkway Central Library", body)
            self.assertNotIn("Charles Santore Library — School Age", body)
        self.assertEqual(
            payload["metadata"]["supplemental_age_failures"],
            ["Parkway Central Library — Young Adult could not be loaded"],
        )
        self.assertEqual(
            payload["metadata"]["supplemental_age_limitations"],
            ["Charles Santore Library — School Age reached its 10-item limit"],
        )

    def test_digest_prioritizes_event_and_omits_unknown_facts(self) -> None:
        event = digest.Event(
            title="Baby & Toddler Storytime!",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10, 30),
            description="Stories, songs, rhymes, and bounces for ages 2 and under.",
            link="https://libwww.freelibrary.org/calendar/event/166375",
            image_url="https://example.test/full-flyer.jpg",
            branch=digest.BRANCHES["CEN"],
            end_at=digest.datetime(2026, 7, 20, 11, 30),
        )
        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 1, 15),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["CEN"]],
            reference_date=date(2026, 7, 18),
            events=[event],
            source_counts={"Parkway Central Library": 1},
        )

        card = payload["html"]
        self.assertIn("Here is 1 activity", card)
        self.assertNotIn("event was checked", card)
        self.assertEqual(payload["metadata"]["scanned_count"], 1)
        self.assertIn(f"10:30 AM {digest.EN_DASH} 11:30 AM", card)
        self.assertNotIn(">Ends</td>", card)
        self.assertNotIn("Registration</td>", card)
        self.assertNotIn("Cost</td>", card)
        self.assertNotIn("object-fit:cover", card)
        self.assertIn("object-fit:contain", card)
        self.assertNotIn("Why included", card)
        self.assertNotIn("The published maximum age includes Avery.", card)
        self.assertNotIn(digest.BRANCHES["CEN"].address, card)
        self.assertNotIn("215-686-5322", card)
        self.assertIn(
            "https://www.google.com/maps/search/?api=1&amp;query=Parkway+Central+Library",
            card,
        )
        self.assertNotIn(">Directions</a>", card)
        self.assertNotIn(">Event details</a>", card)
        self.assertNotIn("calendar placeholder", digest.google_calendar_url(event, 60))

        message = payload["message"]
        self.assertIn(
            f"10:30 AM {digest.EN_DASH} 11:30 AM | Baby & Toddler Storytime!",
            message,
        )
        self.assertNotIn("Ends:", message)
        self.assertNotIn("Why included", message)
        self.assertNotIn("The published maximum age includes Avery.", message)
        self.assertNotIn(digest.BRANCHES["CEN"].address, message)
        self.assertNotIn("215-686-5322", message)
        self.assertIn(
            f"Parkway Central Library: {digest.directions_url(digest.BRANCHES['CEN'])}",
            message,
        )
        self.assertNotIn("Directions:", message)

    def test_child_name_is_configurable(self) -> None:
        payload = digest.build_digest(
            child_name="Morgan",
            birth_date=date(2025, 1, 15),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["IND"]],
            reference_date=date(2026, 7, 17),
            events=[],
            source_counts={"IND": 0},
        )
        self.assertIn("for Morgan", payload["subject"])
        self.assertIn("LIBRARY FUN FOR MORGAN", payload["message"])
        self.assertIn("Library fun for Morgan", payload["html"])


if __name__ == "__main__":
    unittest.main()
