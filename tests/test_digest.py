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
            "<eventimage></eventimage>"
            "</item>"
        )
    return "<?xml version='1.0'?><rss><channel>" + "".join(rows) + "</channel></rss>"


class DigestTests(unittest.TestCase):
    def test_next_week_start_treats_monday_as_current_week(self) -> None:
        self.assertEqual(digest.next_week_start(date(2026, 7, 20)), date(2026, 7, 20))
        self.assertEqual(digest.next_week_start(date(2026, 7, 17)), date(2026, 7, 20))

    def test_age_on_event_date(self) -> None:
        self.assertEqual(digest.age_on(date(2025, 1, 15), date(2026, 7, 24)), (1, 6, 9))
        self.assertEqual(
            digest.format_age(date(2025, 1, 15), date(2026, 7, 24)),
            "1 year, 6 months, 9 days",
        )

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
        fit = digest.classify_event(event, date(2025, 1, 15))
        self.assertEqual(fit.rank, "exclude")

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
                    digest.classify_event(event, date(2025, 1, 15)).rank,
                    expected,
                )

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

        self.assertEqual(payload["metadata"]["included_count"], 2)
        self.assertEqual(payload["metadata"]["omitted_count"], 1)
        self.assertEqual(payload["metadata"]["included_event_ids"], ["1001", "1003"])
        self.assertIn("calendar.google.com/calendar/render", payload["html"])
        self.assertIn("Avery will be", payload["html"])
        self.assertIn("18 South 7th Street", payload["html"])

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
