"""Tests for bounded SMTP image preparation and cleanup."""

from __future__ import annotations

import asyncio
from datetime import date, time
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from custom_components.free_library_events import email_images
from custom_components.free_library_events.digest import BRANCHES, Event

_PNG = b"\x89PNG\r\n\x1a\n" + (b"test" * 8)


class _Content:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def readexactly(self, size: int) -> bytes:
        if len(self._content) < size:
            raise asyncio.IncompleteReadError(self._content, size)
        return self._content[:size]


class _Response:
    def __init__(
        self,
        content: bytes,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.content_length = len(content)
        self.content = _Content(content)
        self.headers = headers or {}

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.requests.append((url, kwargs))
        return self.responses[url]


def _event(title: str, image_url: str) -> Event:
    return Event(
        title=title,
        event_date=date(2026, 7, 20),
        start_time=time(10, 30),
        description="Stories for children.",
        link="https://libwww.freelibrary.org/calendar/event/1001",
        image_url=image_url,
        branch=BRANCHES["CEN"],
        age_categories=("Toddler",),
    )


class EmailImageTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_unique_supported_images_without_redirects(self) -> None:
        first_url = "https://libwww.freelibrary.org/images/first.png"
        bad_url = "https://libwww.freelibrary.org/images/not-an-image"
        session = _Session(
            {
                first_url: _Response(_PNG),
                bad_url: _Response(b"not an image"),
            }
        )

        batch = await email_images.async_download_event_images(
            session,  # type: ignore[arg-type]
            [
                _event("First event", first_url),
                _event("Duplicate flyer", first_url),
                _event("Bad flyer", bad_url),
            ],
        )

        self.assertEqual(batch.requested_count, 2)
        self.assertEqual(len(batch.images), 1)
        self.assertEqual(batch.images[0].extension, ".png")
        self.assertEqual(batch.failure_count, 1)
        self.assertIn("Bad flyer", batch.failure_examples[0])
        self.assertEqual(len(session.requests), 2)
        self.assertTrue(
            all(request[1]["allow_redirects"] is False for request in session.requests)
        )

    async def test_image_count_limit_is_deterministic_and_observable(self) -> None:
        first_url = "https://libwww.freelibrary.org/images/first.png"
        second_url = "https://libwww.freelibrary.org/images/second.png"
        session = _Session({first_url: _Response(_PNG)})

        with patch.object(email_images, "MAX_EMBEDDED_IMAGES", 1):
            batch = await email_images.async_download_event_images(
                session,  # type: ignore[arg-type]
                [_event("First event", first_url), _event("Second event", second_url)],
            )

        self.assertEqual(batch.requested_count, 2)
        self.assertEqual(len(batch.images), 1)
        self.assertEqual(batch.failure_count, 1)
        self.assertIn("count limit", batch.failure_examples[0])
        self.assertEqual([request[0] for request in session.requests], [first_url])
        self.assertEqual(batch.fallback_urls, (second_url,))

    async def test_total_size_limit_keeps_earlier_images_and_falls_back(self) -> None:
        first_url = "https://libwww.freelibrary.org/images/first.png"
        second_url = "https://libwww.freelibrary.org/images/second.png"
        session = _Session(
            {
                first_url: _Response(_PNG),
                second_url: _Response(_PNG),
            }
        )

        with patch.object(email_images, "MAX_TOTAL_IMAGE_BYTES", len(_PNG) + 1):
            batch = await email_images.async_download_event_images(
                session,  # type: ignore[arg-type]
                [_event("First event", first_url), _event("Second event", second_url)],
            )

        self.assertEqual([image.source_url for image in batch.images], [first_url])
        self.assertEqual(batch.failure_count, 1)
        self.assertIn("size limit", batch.failure_examples[0])
        self.assertEqual(batch.fallback_urls, (second_url,))

    async def test_rejects_non_publisher_image_urls_before_request(self) -> None:
        session = _Session({})

        batch = await email_images.async_download_event_images(
            session,  # type: ignore[arg-type]
            [_event("Untrusted flyer", "https://example.test/private.png")],
        )

        self.assertEqual(batch.requested_count, 0)
        self.assertEqual(batch.images, ())
        self.assertEqual(session.requests, [])

    async def test_follows_only_bounded_trusted_redirects_and_classifies_layout(
        self,
    ) -> None:
        first_url = "https://libwww.freelibrary.org/images/start.png"
        final_url = "https://libwww.freelibrary.org/images/final.png"
        landscape_png = (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + (1200).to_bytes(4, "big")
            + (600).to_bytes(4, "big")
            + b"rest"
        )
        session = _Session(
            {
                first_url: _Response(b"", 302, {"Location": "/images/final.png"}),
                final_url: _Response(landscape_png),
            }
        )

        batch = await email_images.async_download_event_images(
            session,  # type: ignore[arg-type]
            [_event("Landscape flyer", first_url)],
        )

        self.assertEqual(
            [request[0] for request in session.requests], [first_url, final_url]
        )
        self.assertEqual((batch.images[0].width, batch.images[0].height), (1200, 600))
        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle = email_images.store_downloaded_images(
                Path(temporary_directory), batch
            )
            self.assertEqual(bundle.source_url_to_layout[first_url], "hero")

    def test_reads_jpeg_dimensions_and_classifies_realistic_flyer_layouts(
        self,
    ) -> None:
        jpeg = (
            b"\xff\xd8\xff\xc0\x00\x11\x08"
            + (600).to_bytes(2, "big")
            + (1200).to_bytes(2, "big")
            + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
            + b"\xff\xd9"
        )

        dimensions = email_images._image_dimensions(jpeg, ".jpg")

        self.assertEqual(dimensions, (1200, 600))
        image = email_images.DownloadedImage(
            "https://libwww.freelibrary.org/images/flyer.jpg",
            jpeg,
            ".jpg",
            *dimensions,
        )
        self.assertEqual(email_images._image_layout(image), "hero")

    async def test_remote_fallback_is_reason_aware(self) -> None:
        unavailable_url = "https://libwww.freelibrary.org/images/unavailable.png"
        challenged_url = "https://libwww.freelibrary.org/images/challenged.png"
        missing_url = "https://libwww.freelibrary.org/images/missing.png"
        invalid_url = "https://libwww.freelibrary.org/images/invalid.png"
        unsafe_url = "https://libwww.freelibrary.org/images/redirect.png"
        session = _Session(
            {
                unavailable_url: _Response(b"", 503),
                challenged_url: _Response(b"challenge", 403),
                missing_url: _Response(b"", 404),
                invalid_url: _Response(b"not an image"),
                unsafe_url: _Response(
                    b"", 302, {"Location": "https://example.test/image.png"}
                ),
            }
        )

        batch = await email_images.async_download_event_images(
            session,  # type: ignore[arg-type]
            [
                _event("Unavailable", unavailable_url),
                _event("Cloudflare challenge", challenged_url),
                _event("Missing", missing_url),
                _event("Invalid", invalid_url),
                _event("Unsafe redirect", unsafe_url),
            ],
        )

        self.assertEqual(batch.fallback_urls, (unavailable_url, challenged_url))
        self.assertEqual(batch.failure_count, 5)

    def test_storage_uses_cid_basenames_and_removes_only_managed_runs(self) -> None:
        batch = email_images.ImageDownloadBatch(
            images=(
                email_images.DownloadedImage(
                    "https://libwww.freelibrary.org/images/first.png", _PNG, ".png"
                ),
            ),
            requested_count=1,
            failure_count=0,
            failure_examples=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "email-images"
            bundle = email_images.store_downloaded_images(root, batch)
            unmanaged = root / "keep-me"
            unmanaged.mkdir()

            self.assertEqual(len(bundle.paths), 1)
            self.assertEqual(Path(bundle.paths[0]).name, "event-01.png")
            self.assertEqual(
                bundle.source_url_to_cid[batch.images[0].source_url],
                "cid:event-01.png",
            )
            self.assertTrue(Path(bundle.paths[0]).is_file())

            email_images.purge_stored_image_runs(root)

            self.assertFalse(bundle.run_directory.exists())
            self.assertTrue(unmanaged.is_dir())

    def test_stale_cleanup_preserves_fresh_managed_run(self) -> None:
        batch = email_images.ImageDownloadBatch(
            images=(email_images.DownloadedImage("source", _PNG, ".png"),),
            requested_count=1,
            failure_count=0,
            failure_examples=(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "email-images"
            stale = email_images.store_downloaded_images(root, batch)
            fresh = email_images.store_downloaded_images(root, batch)
            stale_marker = stale.run_directory / ".managed-by-free-library-events"
            os.utime(stale_marker, (100, 100))

            email_images.purge_stale_image_runs(root, 200)

            self.assertFalse(stale.run_directory.exists())
            self.assertTrue(fresh.run_directory.exists())


if __name__ == "__main__":
    unittest.main()
