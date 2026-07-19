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
            ("Adult",),
        )
        self.assertEqual(
            digest.source_age_categories_for_window(
                date(2008, 8, 15),
                date(2026, 6, 1),
                date(2026, 9, 1),
            ),
            ("Baby", "Toddler", "Preschool", "School Age", "Young Adult", "Adult"),
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
            description="Stories, songs, rhymes, and movement for babies.",
            description_html=(
                '<p class="event-description-paragraph"><strong>Stories</strong>, '
                "songs, rhymes, and movement for babies.</p>"
            ),
            image_url="https://libwww.freelibrary.org/assets/images/event.jpg",
            age_categories=("Toddler",),
            end_at=digest.datetime(2026, 7, 20, 11, 30),
            description_links=(
                digest.DescriptionLink("Resource", "https://example.test/resource"),
            ),
            venue="Sister Cities Park",
            room="Storyhour Room",
        )

        merged = digest.merge_events((base, richer))[0]

        self.assertEqual(merged.description, richer.description)
        self.assertEqual(merged.image_url, richer.image_url)
        self.assertEqual(merged.end_at, richer.end_at)
        self.assertEqual(merged.description_links, richer.description_links)
        self.assertEqual(merged.description_html, richer.description_html)
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

        self.assertEqual(
            digest._repair_bare_numeric_entities("We#39;ll keep #0; literal."),
            "We'll keep #0; literal.",
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

    def test_parser_bounds_remote_item_fields_and_item_count(self) -> None:
        valid = {
            "title": "07/22/26: Baby Music - Charles Santore Library",
            "description": "A music program for babies and caregivers.",
            "date": "07/22/26",
            "time": "10:30 A.M.",
            "branch": "Charles Santore Library",
            "link": "https://example.test/good",
        }
        oversized = valid | {
            "title": "X" * (digest.MAX_EVENT_TITLE_LENGTH + 1),
            "link": "https://example.test/oversized",
        }
        rows = [valid, oversized, *([oversized] * digest.MAX_PARSED_RSS_ITEMS)]

        events, source_count = digest.parse_feed(
            rss(rows), digest.BRANCHES["SWK"], "Baby"
        )

        self.assertEqual(source_count, len(rows))
        self.assertEqual(
            [event.link for event in events], ["https://example.test/good"]
        )

    def test_parser_keeps_trusted_publisher_dotfile_image_names(self) -> None:
        item = {
            "title": "07/25/26: Family Storytime - Charles Santore Library",
            "description": "An inclusive storytime where all children can take part.",
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "https://example.test/events/171403",
            "image_url": (
                "https://libwww.freelibrary.org/assets/images/calendar/"
                "events/2026\\11\\.jpg"
            ),
        }

        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )

        self.assertEqual(
            events[0].image_url,
            "https://libwww.freelibrary.org/assets/images/calendar/events/2026/11/.jpg",
        )

        item["image_url"] = (
            "https://libwww.freelibrary.org/assets/images/calendar/"
            "events/2026/11/171403.jpg"
        )
        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )
        self.assertEqual(events[0].image_url, item["image_url"])

        item["image_url"] = ""
        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )
        self.assertEqual(events[0].image_url, "")

    def test_description_preserves_paragraphs_safe_links_and_rich_formatting(
        self,
    ) -> None:
        raw_description = (
            '<p onclick="alert(1)">First <strong>important</strong> paragraph.</p>'
            "<p>Second <em>gentle</em> paragraph with "
            '<a href="https://example.test/guide" style="position:fixed">'
            "a guide</a>.</p>"
            "<ul><li>One useful detail</li><li>Another detail</li></ul>"
            '<script>alert("unsafe")</script>'
            '<a href="javascript:alert(1)">unsafe link</a>'
        )
        description, links = digest._description_data(
            raw_description,
            "",
        )
        description_html = digest._description_render_html(raw_description, "")

        self.assertEqual(
            description,
            (
                "First important paragraph.\n\n"
                "Second gentle paragraph with a guide.\n\n"
                "One useful detail\n\nAnother detail\n\nunsafe link"
            ),
        )
        self.assertEqual(
            links,
            (digest.DescriptionLink("a guide", "https://example.test/guide"),),
        )

        event = digest.Event(
            title="Family Storytime with AAC",
            event_date=date(2026, 7, 25),
            start_time=digest.time(11),
            description=description,
            link="https://libwww.freelibrary.org/calendar/event/171403",
            image_url=(
                "https://libwww.freelibrary.org/assets/images/calendar/"
                "events/2026/11/.jpg"
            ),
            branch=digest.BRANCHES["SWK"],
            age_categories=("Baby", "Toddler", "Preschool"),
            description_links=links,
            description_html=description_html,
        )
        card = digest._render_event_card(event, duration_minutes=60)

        self.assertEqual(card.count('class="event-description-paragraph"'), 3)
        self.assertIn("<strong>important</strong>", card)
        self.assertIn("<em>gentle</em>", card)
        self.assertIn("<ul", card)
        self.assertIn("<li", card)
        self.assertIn('href="https://example.test/guide"', card)
        self.assertNotIn("onclick", card)
        self.assertNotIn("position:fixed", card)
        self.assertNotIn("javascript:", card)
        self.assertNotIn("alert", card)
        self.assertIn('class="event-heading-cell"', card)
        self.assertIn('class="event-body-cell"', card)
        self.assertIn('class="event-card-shell"', card)
        self.assertIn("padding:0 0 12px", card)
        self.assertNotIn('<div style="margin:0 0 12px', card)
        self.assertIn('colspan="2"', card)
        self.assertIn('class="event-poster-image-cell" colspan="2"', card)
        self.assertIn(f'width="{digest.EMAIL_POSTER_IMAGE_WIDTH}"', card)
        self.assertIn(
            f"width:100%;max-width:{digest.EMAIL_POSTER_IMAGE_WIDTH}px;"
            "height:auto;margin:0 auto",
            card,
        )
        self.assertNotIn("background:#f8fafd", card)
        self.assertIn("border-top:1px solid #eef1f5", card)
        self.assertIn(
            'alt="View official event details for Family Storytime with AAC"',
            card,
        )
        self.assertIn("<strong>Library age listing:</strong>", card)
        self.assertNotIn("<strong>Ages:</strong>", card)
        self.assertLess(
            card.index('class="event-audience"'),
            card.index('class="event-description-paragraph"'),
        )
        self.assertIn('<span aria-hidden="true">', card)

    def test_rich_description_strips_trailer_and_balances_malformed_markup(
        self,
    ) -> None:
        trailer = "07/25/26, 11:00 A.M. - Charles Santore Library"
        rendered = digest._description_render_html(
            f"<p><strong>Bold <em>nested</p><p>{trailer}</p>",
            trailer,
        )

        self.assertIn("<strong>Bold <em>nested</em></strong>", rendered)
        self.assertNotIn(trailer, rendered)
        self.assertEqual(rendered.count('class="event-description-paragraph"'), 1)

    def test_event_chips_show_all_useful_source_backed_context(self) -> None:
        event = digest.Event(
            title="Inclusive outdoor program",
            event_date=date(2026, 7, 25),
            start_time=digest.time(11),
            description=(
                "Join our AAC storytime and music program, then stay for playgroup "
                "and playtime. This outdoor program has a to-go craft while supplies "
                "last. Kids of all ages are welcome. "
                "Siblings are welcome. In unfavorable weather it will be cancelled. "
                "Registration is required. All participants receive AAC boards to "
                "take home."
            ),
            link="https://libwww.freelibrary.org/calendar/event/171403",
            image_url="",
            branch=digest.BRANCHES["SWK"],
            age_categories=("Baby", "Toddler", "Preschool"),
        )

        card = digest._render_event_card(event, duration_minutes=60)

        self.assertIn('class="event-highlights"', card)
        self.assertIn(
            "<strong>Library age listing:</strong> Baby · Toddler · Preschool",
            card,
        )
        self.assertNotIn(">Toddler</span>", card)
        self.assertNotIn(">Preschool</span>", card)
        for label in (
            "Registration required",
            "Weather dependent",
            "Limited supplies",
            "Outdoors",
            "Take-home craft",
        ):
            self.assertIn(f">{label}</span>", card)
        self.assertEqual(len(digest._event_chip_specs(event)), digest.MAX_EVENT_CHIPS)
        self.assertNotIn(">Crafts</span>", card)
        for generic_label in ("Family Programs", "Storytimes", "Children", "Family"):
            self.assertNotIn(f">{generic_label}</span>", card)
        self.assertIn("#477a00", card)
        self.assertIn("#cf102d", card)
        self.assertIn("font-size:12px", card)
        self.assertLess(
            card.index(">Registration required</span>"),
            card.index("Join our AAC storytime"),
        )

        topic_card = digest._render_event_card(
            digest.replace(
                event,
                title="Inclusive program",
                description="An AAC storytime with live music.",
            ),
            duration_minutes=60,
        )
        for label in ("AAC", "Storytime", "Music"):
            self.assertIn(f">{label}</span>", topic_card)
        self.assertIn("#1c6984", topic_card)

        no_registration_event = digest.replace(
            event,
            description="This outdoor AAC program requires no registration.",
        )
        self.assertNotIn(
            "Registration required",
            digest._render_event_card(no_registration_event, duration_minutes=60),
        )

        title_repeats = digest.replace(
            event,
            title="AAC Music Storytime, Playgroup, Playtime, and Crafternoon",
            description="Kids of all ages are welcome.",
        )
        repeated_labels = {
            label for _kind, label in digest._event_chip_specs(title_repeats)
        }
        for redundant_label in (
            "AAC",
            "Music",
            "Storytime",
            "Playgroup",
            "Playtime",
            "Crafts",
        ):
            self.assertNotIn(redundant_label, repeated_labels)

        broad_published_audience = digest.replace(
            event,
            description="Toys for a range of ages.",
            age_categories=("Toddler", "Preschool", "School Age"),
        )
        self.assertNotIn(
            "Broad ages",
            {
                label
                for _kind, label in digest._event_chip_specs(broad_published_audience)
            },
        )
        narrow_published_audience = digest.replace(
            broad_published_audience,
            age_categories=("Toddler",),
        )
        self.assertIn(
            "Broad ages",
            {
                label
                for _kind, label in digest._event_chip_specs(narrow_published_audience)
            },
        )

        incidental_music = digest.replace(
            event,
            title="Baby and Toddler Playtime",
            description="Play with toys while listening to music.",
        )
        self.assertNotIn(
            "Music",
            {label for _kind, label in digest._event_chip_specs(incidental_music)},
        )

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

    def test_parser_rejects_malformed_or_credentialed_urls_without_losing_item(
        self,
    ) -> None:
        item = {
            "title": "07/25/26: Family Storytime - Charles Santore Library",
            "description": (
                'Read the <a href="https://user:pass@example.test/guide">guide</a>.'
            ),
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "http://[::1",
            "image_url": "http://[::1",
        }

        events, source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )

        self.assertEqual(source_count, 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].link, "")
        self.assertEqual(events[0].image_url, "")
        self.assertEqual(events[0].description_links, ())

        item["link"] = "https://example.test/" + ("x" * digest.MAX_URL_LENGTH)
        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )
        self.assertEqual(events[0].link, "")

    def test_parser_does_not_auto_load_images_from_untrusted_hosts(self) -> None:
        item = {
            "title": "07/25/26: Family Storytime - Charles Santore Library",
            "description": "An inclusive storytime for children and caregivers.",
            "date": "07/25/26",
            "time": "11:00 A.M.",
            "branch": "Charles Santore Library",
            "link": "https://libwww.freelibrary.org/calendar/event/171403",
            "image_url": "https://tracking.example.test/open.gif",
        }

        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )

        self.assertEqual(events[0].image_url, "")

        item["image_url"] = (
            "http://libwww.freelibrary.org/assets/images/calendar/events/171403.jpg"
        )
        events, _source_count = digest.parse_feed(
            rss([item]), digest.BRANCHES["SWK"], "Toddler"
        )
        self.assertEqual(events[0].image_url, "")

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
                "<strong>Learn about</strong> "
                '<a href="https://www.asha.org/public/speech/disorders/aac/">'
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
        self.assertIn("<strong>Learn about</strong>", event.description_html)
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
                self.assertEqual(
                    digest.event_location_summary(event),
                    f"{expected} {digest.MIDDLE_DOT} Hosted by Parkway Central Library",
                )
                card = digest._render_event_card(event, duration_minutes=60)
                self.assertIn(f"&nbsp;{expected}</a>", card)
                self.assertIn("Hosted by Parkway Central Library", card)
                compact_card = digest._render_event_card(
                    event, duration_minutes=60, compact=True
                )
                self.assertIn(f"&nbsp;{expected}</a>", compact_card)
                self.assertIn("Hosted by Parkway Central Library", compact_card)
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

    def test_child_name_is_single_line_and_bounded_for_email_headers(self) -> None:
        self.assertEqual(
            digest.normalize_child_name("  Avery\r\n Quinn  "), "Avery Quinn"
        )
        with self.assertRaisesRegex(ValueError, "invalid_child_name"):
            digest.normalize_child_name(None)
        with self.assertRaisesRegex(ValueError, "invalid_child_name"):
            digest.normalize_child_name("A" * (digest.MAX_CHILD_NAME_LENGTH + 1))

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

    def test_explicit_age_ranges_support_newborn_and_mixed_units(self) -> None:
        cases = (
            ("Children from newborn through age 5 are welcome.", "best"),
            ("Designed for children ages 6 months to 3 years.", "best"),
            ("Designed for children ages 2 years to 5 years.", "exclude"),
        )
        for description, expected in cases:
            with self.subTest(description=description):
                event = digest.Event(
                    title="Family Program",
                    event_date=date(2026, 7, 21),
                    start_time=digest.time(13, 0),
                    description=description,
                    link="https://example.test/age-range",
                    image_url="",
                    branch=digest.BRANCHES["IND"],
                    age_categories=("School Age",),
                )
                self.assertEqual(
                    digest.classify_event(event, date(2025, 11, 7)), expected
                )

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

        self.assertEqual(
            payload["subject"],
            "4 library activities for Avery 📚 · Jul 20–26",
        )
        self.assertEqual(payload["metadata"]["included_count"], 4)
        self.assertEqual(payload["metadata"]["omitted_count"], 1)
        self.assertEqual(
            payload["metadata"]["included_event_ids"],
            ["1001", "1004", "1005", "1003"],
        )
        self.assertIn("calendar.google.com/calendar/render", payload["html"])
        self.assertNotIn(">Other calendars</a>", payload["html"])
        self.assertIn('class="email-button"', payload["html"])
        self.assertIn('class="email-button-cell" bgcolor="#1967d2"', payload["html"])
        self.assertIn("padding:13px 16px", payload["html"])
        self.assertIn("line-height:160%", payload["html"])
        self.assertNotRegex(
            payload["html"],
            r"line-height:\d+(?:\.\d+)?(?=[;\"'])",
        )
        self.assertIn("mso-hide:all", payload["html"])
        self.assertIn("opacity:0", payload["html"])
        self.assertIn('class="event-day-heading"', payload["html"])
        self.assertIn('class="event-day-spacer"', payload["html"])
        self.assertNotIn('<div style="margin:0 0 24px">', payload["html"])
        self.assertIn(
            "The library did not publish end times for these activities; "
            "Google Calendar uses a "
            "60-minute placeholder for those activities.",
            payload["html"],
        )
        self.assertIn(
            "Wednesday–Friday from 4 libraries, with directions and calendar links.",
            payload["html"],
        )
        self.assertNotIn("4 age-matched library activities for Avery", payload["html"])
        self.assertIn(
            "4 activities selected for Avery’s age across 4 libraries.",
            payload["html"],
        )
        self.assertNotIn("Listed for:", payload["html"])
        self.assertNotIn("Listed for:", payload["message"])
        self.assertNotIn("who is 18 months old", payload["html"])
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
        self.assertIn("@media only screen and (max-width:620px)", payload["html"])
        self.assertEqual(digest.EMAIL_POSTER_IMAGE_WIDTH, 440)
        self.assertIn(
            ".event-poster-image-cell img "
            "{width:100%!important;max-width:100%!important;"
            "height:auto!important;margin:0 auto!important}",
            payload["html"],
        )
        self.assertIn("@media only screen and (max-width:390px)", payload["html"])
        self.assertNotIn(".event-image-cell", payload["html"])
        self.assertIn('class="email-shell"', payload["html"])
        self.assertIn('class="email-header"', payload["html"])
        self.assertIn('class="email-title"', payload["html"])
        self.assertIn('class="email-content"', payload["html"])
        self.assertIn('class="email-footer"', payload["html"])
        self.assertIn('class="event-title"', payload["html"])
        self.assertIn('class="event-meta"', payload["html"])
        self.assertIn('class="event-time"', payload["html"])
        self.assertIn('class="event-location"', payload["html"])
        self.assertIn('class="event-location-link"', payload["html"])
        self.assertIn(
            'class="event-location-link" href=',
            payload["html"],
        )
        self.assertIn(
            'text-underline-offset:3px"><span aria-hidden="true">'
            "&#128205;</span>&nbsp;",
            payload["html"],
        )
        self.assertNotIn(
            '<div class="event-location" style="margin:2px 0 0">'
            '<span aria-hidden="true">&#128205;</span> <a ',
            payload["html"],
        )
        self.assertIn('class="branch-calendar-table"', payload["html"])
        self.assertEqual(payload["html"].count('class="branch-calendar-cell"'), 4)
        self.assertEqual(payload["html"].count('class="branch-calendar-link"'), 4)
        self.assertIn(".event-highlights {margin-top:6px!important}", payload["html"])
        self.assertIn('class="email-button-cell"', payload["html"])
        self.assertIn('class="email-button-link"', payload["html"])
        self.assertIn(
            ".event-description-paragraph,.event-description-list "
            "{font-size:16px!important;line-height:155%!important}",
            payload["html"],
        )
        self.assertIn(
            ".email-button-cell {padding:14px 16px!important;"
            "text-align:center!important}",
            payload["html"],
        )
        self.assertIn(
            ".event-location-link {display:block!important;padding:13px 0!important}",
            payload["html"],
        )
        self.assertIn(
            ".branch-calendar-link {padding:13px 10px!important;font-size:15px!important}",
            payload["html"],
        )
        self.assertIn(
            ".branch-calendar-cell {display:block!important;width:auto!important}",
            payload["html"],
        )
        self.assertIn("html,body {color-scheme:only light}", payload["html"])
        self.assertNotIn("color-scheme:light only", payload["html"])
        self.assertIn("Browse full branch calendars:", payload["html"])
        self.assertNotIn("See every published event:", payload["html"])

    def test_branch_distance_prioritization_never_renders_distance_copy(self) -> None:
        branch_event = digest.Event(
            title="Baby Storytime",
            event_date=date(2026, 7, 22),
            start_time=digest.time(10, 30),
            description="Stories for babies.",
            link="https://example.test/events/branch",
            image_url="",
            branch=digest.BRANCHES["SWK"],
            age_categories=("Baby",),
        )
        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 11, 1),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=(digest.BRANCHES["SWK"],),
            reference_date=date(2026, 7, 19),
            events=[branch_event],
            source_counts={"SWK": 1},
            distance_by_branch_code={"SWK": 1_609.344},
        )

        self.assertIn('class="event-time"', payload["html"])
        self.assertIn('class="event-location"', payload["html"])
        self.assertIn('class="event-location-link"', payload["html"])
        self.assertNotRegex(payload["html"], r"(?:~|&lt;)?\d+(?:\.\d+)?\s*mi\b")
        self.assertNotIn("distance", payload["html"].lower())
        self.assertNotRegex(payload["message"], r"(?:~|<)?\d+(?:\.\d+)?\s*mi\b")
        self.assertNotIn("distance", payload["message"].lower())
        self.assertEqual(payload["html"].count('class="branch-calendar-cell"'), 1)
        self.assertEqual(payload["html"].count('class="branch-calendar-empty"'), 1)

        offsite_card = digest._render_event_card(
            digest.replace(branch_event, venue="Sister Cities Park"),
            duration_minutes=60,
        )
        self.assertNotRegex(offsite_card, r"(?:~|&lt;)?\d+(?:\.\d+)?\s*mi\b")

    def test_calendar_placeholder_note_distinguishes_all_some_and_none(self) -> None:
        event = digest.Event(
            title="Storytime",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10, 30),
            description="Stories for young children.",
            link="https://example.test/events/placeholder",
            image_url="",
            branch=digest.BRANCHES["CEN"],
        )
        with_end = digest.replace(
            event,
            title="Music class",
            end_at=digest.datetime(2026, 7, 20, 11, 30),
        )

        self.assertEqual(
            digest._calendar_placeholder_note([event], 60),
            "The library did not publish end times for these activities; "
            "Google Calendar uses a 60-minute placeholder for those activities.",
        )
        self.assertEqual(
            digest._calendar_placeholder_note([event, with_end], 60),
            "Some end times are not published; Google Calendar uses a 60-minute "
            "placeholder for those activities.",
        )
        self.assertEqual(digest._calendar_placeholder_note([with_end], 60), "")

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
                "Some library listings may be missing. Check the full branch "
                "calendars below.",
                body,
            )
            self.assertNotIn(
                "Philadelphia City Institute — Toddler reached its 10-item limit",
                body,
            )
            self.assertNotIn("could not load: Parkway Central Library", body)
            self.assertNotIn("Charles Santore Library — School Age", body)
        self.assertLess(
            payload["html"].index("Some library listings may be missing."),
            payload["html"].index("Browse full branch calendars:"),
        )
        self.assertLess(
            payload["message"].index("Some library listings may be missing."),
            payload["message"].index("Full branch calendars:"),
        )
        self.assertEqual(
            payload["metadata"]["source_errors"], ["Parkway Central Library"]
        )
        self.assertEqual(
            payload["metadata"]["source_warnings"],
            ["Philadelphia City Institute — Toddler reached its 10-item limit"],
        )
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
        self.assertIn(
            "1 activity selected for Avery’s age at 1 library.",
            card,
        )
        self.assertNotIn("event was checked", card)
        self.assertEqual(payload["metadata"]["scanned_count"], 1)
        self.assertIn(f"10:30 AM {digest.EN_DASH} 11:30 AM", card)
        self.assertNotIn(">Ends</td>", card)
        self.assertNotIn("Registration</td>", card)
        self.assertNotIn("Cost</td>", card)
        self.assertNotIn("object-fit:cover", card)
        self.assertIn("width:100%;max-width:440px;height:auto", card)
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
        self.assertNotIn(">Other calendars</a>", card)
        self.assertNotIn("calendar placeholder", digest.google_calendar_url(event, 60))
        self.assertNotIn("End time not published", card)

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

    def test_digest_can_replace_remote_images_with_cid_or_omit_them(self) -> None:
        first = digest.Event(
            title="Embedded flyer",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10, 30),
            description="Stories for children ages 2 and under.",
            link="https://libwww.freelibrary.org/calendar/event/1001",
            image_url="https://libwww.freelibrary.org/images/first.png",
            branch=digest.BRANCHES["CEN"],
        )
        second = digest.replace(
            first,
            title="Unavailable flyer",
            link="https://libwww.freelibrary.org/calendar/event/1002",
            image_url="https://libwww.freelibrary.org/images/second.png",
        )
        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 1, 15),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["CEN"]],
            reference_date=date(2026, 7, 18),
            events=[first, second],
            source_counts={"Parkway Central Library": 2},
            image_url_overrides={
                digest.event_identity(first): "cid:event-01.png",
                digest.event_identity(second): "",
            },
        )

        self.assertIn('src="cid:event-01.png"', payload["html"])
        self.assertNotIn(first.image_url, payload["html"])
        self.assertNotIn(second.image_url, payload["html"])
        self.assertEqual(
            payload["html"].count('class="event-poster-image-cell"'),
            1,
        )

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
        self.assertIn(
            "No clearly age-matched activities were published; "
            "check the full branch calendars.",
            payload["html"],
        )

    def test_occurrence_identity_keeps_repeated_series_dates_distinct(self) -> None:
        first = digest.Event(
            title="Recurring storytime",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10),
            description="Stories for babies.",
            link="https://libwww.freelibrary.org/calendar/event/series",
            image_url="",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby",),
        )
        second = digest.replace(first, event_date=date(2026, 7, 22))

        self.assertNotEqual(digest.event_identity(first), digest.event_identity(second))
        self.assertEqual(len(digest.merge_events([first, second])), 2)

        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 10, 7),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=[digest.BRANCHES["CEN"]],
            reference_date=date(2026, 7, 19),
            events=[first, second],
            source_counts={"Parkway Central Library": 2},
        )
        self.assertEqual(
            payload["metadata"]["included_event_ids"], ["series", "series"]
        )
        self.assertEqual(
            payload["metadata"]["included_occurrence_ids"],
            [digest.event_identity(first), digest.event_identity(second)],
        )

    def test_blank_title_restores_the_generic_fallback(self) -> None:
        payload = rss(
            [
                {
                    "title": "   ",
                    "description": "Stories for babies.",
                    "date": "07/20/26",
                    "time": "10:00 A.M.",
                    "branch": "Parkway Central Library",
                    "link": "https://libwww.freelibrary.org/calendar/event/blank",
                }
            ]
        )

        events, _count = digest.parse_feed(payload, digest.BRANCHES["CEN"], "Baby")

        self.assertEqual(events[0].title, "Library event")

    def test_description_sanitizer_normalizes_nested_blocks_and_orphan_text(
        self,
    ) -> None:
        rendered = digest._description_render_html(
            "<div>Outer<p><strong>Nested</strong> paragraph</p>tail</div>"
            "<table><tr><td>Table text</td></tr></table>",
            "",
        )

        self.assertNotRegex(rendered, r"<p[^>]*>[^<]*<p")
        self.assertEqual(rendered.count('<p class="event-description-paragraph"'), 4)
        self.assertIn("<strong>Nested</strong>", rendered)
        self.assertIn(">tail</p>", rendered)
        self.assertIn(">Table text</p>", rendered)

        malformed_list = digest._description_render_html(
            "<ul>Loose text<strong> with emphasis</strong></ul>", ""
        )
        self.assertIn("<ul", malformed_list)
        self.assertIn("<li", malformed_list)
        self.assertNotRegex(malformed_list, r"<ul[^>]*>\s*<p")

    def test_highlights_prioritize_actions_bound_count_and_respect_negation(
        self,
    ) -> None:
        event = digest.Event(
            title="Community gathering",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10),
            description=(
                "Storytime with live music, a playgroup, playtime, crafts, and AAC. "
                "This outdoor event welcomes siblings and kids of all ages. "
                "Receive AAC boards to take home. Weather permitting; while supplies "
                "last. Advance registration is required."
            ),
            link="https://libwww.freelibrary.org/calendar/event/chips",
            image_url="",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby",),
        )

        chips = digest._event_chip_specs(event)

        self.assertLessEqual(len(chips), digest.MAX_EVENT_CHIPS)
        self.assertEqual(chips[0], ("action", "Registration required"))
        self.assertIn(("action", "Weather dependent"), chips)
        self.assertIn(("action", "Limited supplies"), chips)

        location_change = digest.replace(
            event,
            description=(
                "Cooler weather? We will meet indoors. Warmer weather? "
                "We will meet in the park."
            ),
        )
        location_labels = {
            label for _kind, label in digest._event_chip_specs(location_change)
        }
        self.assertIn("Weather affects location", location_labels)
        self.assertNotIn("Weather dependent", location_labels)

        inclement_location_change = digest.replace(
            event,
            description="In inclement weather, the program will move indoors.",
        )
        inclement_labels = {
            label
            for _kind, label in digest._event_chip_specs(inclement_location_change)
        }
        self.assertIn("Weather affects location", inclement_labels)
        self.assertNotIn("Weather dependent", inclement_labels)

        negated = digest.replace(
            event,
            description=(
                "Registration is required for adults only; children may drop in. "
                "AAC boards are not provided. The event will not be cancelled for "
                "weather. No materials are provided."
            ),
        )
        labels = {label for _kind, label in digest._event_chip_specs(negated)}
        self.assertNotIn("Registration required", labels)
        self.assertNotIn("AAC board provided", labels)
        self.assertNotIn("Weather dependent", labels)
        self.assertNotIn("Weather affects location", labels)
        self.assertNotIn("Materials provided", labels)
        self.assertIn("Drop-in", labels)

        american_spelling = digest.replace(
            event,
            description=(
                "Weather update: the event will not be canceled because of the weather."
            ),
        )
        self.assertNotIn(
            "Weather dependent",
            {label for _kind, label in digest._event_chip_specs(american_spelling)},
        )

    def test_online_and_hybrid_events_do_not_get_misleading_map_links(self) -> None:
        online = digest.Event(
            title="Virtual family workshop",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10),
            description="Join us online via Zoom for this virtual program.",
            link="https://libwww.freelibrary.org/calendar/event/online",
            image_url="",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby",),
            modality="online",
        )
        hybrid = digest.replace(
            online,
            description="Attend in person or online via Zoom.",
            modality="hybrid",
        )

        self.assertEqual(digest.event_location_label(online), "Online")
        self.assertEqual(digest.event_directions_url(online), "")
        self.assertEqual(digest.event_calendar_location(online), "Online")
        self.assertIn("Online", digest.event_location_label(hybrid))
        self.assertTrue(digest.event_directions_url(hybrid))

        online_card = digest._render_event_card(online, duration_minutes=60)
        self.assertIn('class="event-location"', online_card)
        self.assertIn("&#128205;</span>&nbsp;Online</div>", online_card)
        self.assertNotIn(">Online</a>", online_card)
        hybrid_card = digest._render_event_card(hybrid, duration_minutes=60)
        self.assertRegex(
            hybrid_card,
            r'class="event-location-link"[^>]*><span aria-hidden="true">'
            r"&#128205;</span>&nbsp;[^<]+</a>",
        )
        self.assertIn(f"</a> {digest.MIDDLE_DOT} Online option", hybrid_card)
        self.assertNotRegex(hybrid_card, r">[^<]*Online option</a>")

        plain_text = digest._render_plain_text(
            [online],
            child_name="Avery",
            birth_date=date(2025, 10, 7),
            week_start=date(2026, 7, 20),
            week_end=date(2026, 7, 26),
            branches=[digest.BRANCHES["CEN"]],
            duration_minutes=60,
            source_errors=(),
            source_warnings=(),
        )
        self.assertIn("Library age listing: Baby", plain_text)
        self.assertIn("\nOnline\n", plain_text)
        self.assertNotIn("\nOnline: \n", plain_text)

    def test_feed_modality_requires_explicit_event_wording(self) -> None:
        items = [
            {
                "title": "Virtual family workshop",
                "description": "Join us online via Zoom for this program.",
                "date": "07/20/26",
                "time": "10:00 A.M.",
                "branch": "Parkway Central Library",
                "link": "https://example.test/online",
            },
            {
                "title": "Hybrid storytime",
                "description": "Attend in person or online via Zoom.",
                "date": "07/21/26",
                "time": "10:00 A.M.",
                "branch": "Parkway Central Library",
                "link": "https://example.test/hybrid",
            },
            {
                "title": "Online play practice",
                "description": "Learn about safe online play through an in-library game.",
                "date": "07/22/26",
                "time": "10:00 A.M.",
                "branch": "Parkway Central Library",
                "link": "https://example.test/in-person",
            },
        ]

        events, _count = digest.parse_feed(rss(items), digest.BRANCHES["CEN"])

        self.assertEqual(
            [event.modality for event in events],
            ["online", "hybrid", "in_person"],
        )

    def test_landscape_images_use_a_full_width_hero_row(self) -> None:
        event = digest.Event(
            title="Family activity",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10),
            description="A family activity for babies.",
            link="https://example.test/hero",
            image_url="cid:event-01.png",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby",),
            image_layout="hero",
        )

        card = digest._render_event_card(event, duration_minutes=60)

        self.assertIn('class="event-hero-image-cell"', card)
        self.assertIn(f'width="{digest.EMAIL_CONTENT_WIDTH}"', card)
        self.assertIn("width:100%;max-width:100%;height:auto", card)
        self.assertNotIn('class="event-image-cell"', card)

    def test_square_images_use_a_media_first_poster_row(self) -> None:
        event = digest.Event(
            title="Baby and Toddler Storytime",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10, 30),
            description="Stories, songs, and playtime for young children.",
            link="https://example.test/poster",
            image_url="cid:event-02.png",
            branch=digest.BRANCHES["CEN"],
            age_categories=("Baby", "Toddler"),
            image_layout="side",
        )

        card = digest._render_event_card(event, duration_minutes=60)

        self.assertIn(
            'class="event-poster-image-cell" colspan="2"',
            card,
        )
        self.assertIn('width="440" align="center"', card)
        self.assertIn(
            "width:100%;max-width:440px;height:auto;margin:0 auto",
            card,
        )
        self.assertIn('class="event-heading-cell" colspan="2"', card)
        self.assertNotIn('class="event-image-cell"', card)
        self.assertLess(
            card.index('class="event-poster-image-cell"'),
            card.index('class="event-heading-cell"'),
        )

    def test_calendar_url_and_distance_prioritized_html_are_bounded(self) -> None:
        description = "A detailed activity description with useful information. " * 80
        events = []
        for index in range(40):
            branch = digest.BRANCHES["SWK"] if index % 2 else digest.BRANCHES["CEN"]
            events.append(
                digest.Event(
                    title=f"General event {index}",
                    event_date=date(2026, 7, 20 + index % 6),
                    start_time=digest.time(9 + index % 8, 30 if index % 2 else 0),
                    description=description,
                    link=f"https://libwww.freelibrary.org/calendar/event/{2000 + index}",
                    image_url="https://libwww.freelibrary.org/images/event.png",
                    branch=branch,
                    age_categories=("Baby",),
                )
            )

        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 11, 1),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=(digest.BRANCHES["SWK"], digest.BRANCHES["CEN"]),
            reference_date=date(2026, 7, 19),
            events=events,
            source_counts={"SWK": 20, "CEN": 20},
            distance_by_branch_code={"SWK": 100.0, "CEN": 10_000.0},
        )

        metadata = payload["metadata"]
        self.assertLessEqual(metadata["html_bytes"], digest.MAX_DIGEST_HTML_BYTES)
        self.assertTrue(metadata["distance_priority_used"])
        self.assertGreater(metadata["compact_card_count"], 0)
        self.assertTrue(metadata["full_card_event_ids"])
        self.assertTrue(
            all(":SWK:" in identity for identity in metadata["full_card_event_ids"])
        )
        self.assertGreater(metadata["truncated_description_count"], 0)
        self.assertLessEqual(
            len(digest.google_calendar_url(events[0], 60)),
            digest.MAX_CALENDAR_URL_LENGTH,
        )

    def test_mobile_layout_keeps_every_card_rich_when_the_html_budget_allows(
        self,
    ) -> None:
        events = []
        for index in range(8):
            branch = digest.BRANCHES["SWK"] if index < 5 else digest.BRANCHES["CEN"]
            events.append(
                digest.Event(
                    title=f"Baby activity {index}",
                    event_date=date(2026, 7, 20 + index % 7),
                    start_time=digest.time(9 + index % 8),
                    description="A useful activity for babies and caregivers.",
                    link=f"https://example.test/events/{index}",
                    image_url="https://libwww.freelibrary.org/images/event.png",
                    branch=branch,
                    age_categories=("Baby",),
                )
            )

        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 11, 1),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=(digest.BRANCHES["SWK"], digest.BRANCHES["CEN"]),
            reference_date=date(2026, 7, 19),
            events=events,
            source_counts={
                "SWK": 5,
                "CEN": 3,
            },
            distance_by_branch_code={"SWK": 100.0, "CEN": 10_000.0},
        )

        metadata = payload["metadata"]
        self.assertEqual(metadata["included_count"], len(events))
        self.assertEqual(metadata["email_omitted_count"], 0)
        self.assertEqual(metadata["full_card_count"], len(events))
        self.assertEqual(metadata["compact_card_count"], 0)
        self.assertFalse(metadata["distance_priority_used"])
        self.assertEqual(payload["html"].count("<img "), len(events))
        self.assertEqual(
            payload["html"].count('class="event-description-paragraph"'), len(events)
        )
        self.assertNotRegex(payload["html"], r"(?:~|&lt;)?\d+(?:\.\d+)?\s*mi\b")
        self.assertNotIn("distance", payload["html"].lower())
        self.assertNotIn(
            "Nearby activities include more detail; every match stays listed.",
            payload["html"],
        )
        self.assertNotIn('class="compact-calendar-link"', payload["html"])

    def test_pathological_event_count_has_an_explicit_bounded_overflow(self) -> None:
        events = [
            digest.Event(
                title=f"Baby activity {index}",
                event_date=date(2026, 7, 20 + index % 7),
                start_time=digest.time(9 + index % 8, index % 60),
                description="A useful activity for babies and caregivers.",
                link=f"https://example.test/events/{index}",
                image_url="",
                branch=(
                    digest.BRANCHES["SWK"] if index % 2 else digest.BRANCHES["CEN"]
                ),
                age_categories=("Baby",),
            )
            for index in range(120)
        ]

        payload = digest.build_digest(
            child_name="Avery",
            birth_date=date(2025, 11, 1),
            filter_mode="Recommended",
            duration_minutes=60,
            selected_branches=(digest.BRANCHES["SWK"], digest.BRANCHES["CEN"]),
            reference_date=date(2026, 7, 19),
            events=events,
            source_counts={"SWK": 60, "CEN": 60},
            distance_by_branch_code={"SWK": 100.0, "CEN": 10_000.0},
        )

        metadata = payload["metadata"]
        self.assertEqual(metadata["included_count"], 120)
        self.assertLessEqual(metadata["html_bytes"], digest.MAX_DIGEST_HTML_BYTES)
        self.assertGreaterEqual(metadata["email_omitted_count"], 20)
        self.assertEqual(
            metadata["full_card_count"]
            + metadata["compact_card_count"]
            + metadata["email_omitted_count"],
            metadata["included_count"],
        )
        self.assertIn("additional matched activities were omitted", payload["html"])

    def test_dynamic_icons_use_words_instead_of_substrings(self) -> None:
        event = digest.Event(
            title="Community Party",
            event_date=date(2026, 7, 20),
            start_time=digest.time(10),
            description="",
            link="",
            image_url="",
            branch=digest.BRANCHES["CEN"],
        )
        self.assertEqual(digest.icon_for(event), "\N{SPARKLES}")
        self.assertEqual(
            digest.icon_for(digest.replace(event, title="Bread Making")),
            "\N{SPARKLES}",
        )
        self.assertEqual(
            digest.icon_for(digest.replace(event, title="Art Workshop")),
            "\N{ARTIST PALETTE}",
        )


if __name__ == "__main__":
    unittest.main()
