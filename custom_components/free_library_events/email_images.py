"""Bounded, deterministic image preparation for SMTP CID embedding."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.mime.image import MIMEImage
from pathlib import Path
import re
import shutil
import urllib.parse
from uuid import uuid4

import aiohttp

from .digest import Event, clean_image_url

EMAIL_IMAGE_DIRECTORY = ".free_library_events_email"
IMAGE_CACHE_TTL_SECONDS = 60 * 60
MAX_EMBEDDED_IMAGES = 12
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_REQUEST_CONCURRENCY = 4
MAX_FAILURE_EXAMPLES = 3

_MANAGED_MARKER = ".managed-by-free-library-events"
_RUN_DIRECTORY_PATTERN = re.compile(r"^run-[0-9a-f]{32}$")
_SUBTYPE_EXTENSIONS = {
    "gif": ".gif",
    "jpeg": ".jpg",
    "png": ".png",
    "webp": ".webp",
}


@dataclass(frozen=True, slots=True)
class DownloadedImage:
    """One validated publisher image held in memory before storage."""

    source_url: str
    content: bytes
    extension: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class ImageDownloadBatch:
    """Bounded image-download result."""

    images: tuple[DownloadedImage, ...]
    requested_count: int
    failure_count: int
    failure_examples: tuple[str, ...]
    fallback_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StoredImageBundle:
    """Stored images and the CID mapping used by the digest renderer."""

    source_url_to_cid: dict[str, str]
    paths: tuple[str, ...]
    run_directory: Path | None
    source_url_to_layout: dict[str, str] = field(default_factory=dict)


class _ImageDownloadFailure(ValueError):
    """A classified image failure with an explicit remote-fallback policy."""

    def __init__(self, message: str, *, allow_remote_fallback: bool) -> None:
        super().__init__(message)
        self.allow_remote_fallback = allow_remote_fallback


def _unique_image_requests(events: Sequence[Event]) -> list[tuple[str, str]]:
    """Return unique image URL and title pairs in digest order."""

    requests: list[tuple[str, str]] = []
    seen: set[str] = set()
    for event in events:
        source_url = clean_image_url(event.image_url)
        if source_url and source_url not in seen:
            seen.add(source_url)
            requests.append((source_url, event.title))
    return requests


def _image_extension(content: bytes) -> str:
    """Return an email-safe extension after stdlib MIME signature detection."""

    try:
        subtype = MIMEImage(content).get_content_subtype()
    except TypeError:
        return ""
    return _SUBTYPE_EXTENSIONS.get(subtype, "")


def _valid_dimensions(width: int, height: int) -> tuple[int, int] | None:
    return (width, height) if 0 < width <= 100_000 and 0 < height <= 100_000 else None


def _image_dimensions(content: bytes, extension: str) -> tuple[int, int] | None:
    """Read common image dimensions without decoding untrusted image pixels."""

    if extension == ".png" and len(content) >= 24 and content.startswith(b"\x89PNG"):
        return _valid_dimensions(
            int.from_bytes(content[16:20], "big"),
            int.from_bytes(content[20:24], "big"),
        )
    if extension == ".gif" and len(content) >= 10:
        return _valid_dimensions(
            int.from_bytes(content[6:8], "little"),
            int.from_bytes(content[8:10], "little"),
        )
    if extension == ".webp" and len(content) >= 30:
        if content[12:16] == b"VP8X":
            return _valid_dimensions(
                1 + int.from_bytes(content[24:27], "little"),
                1 + int.from_bytes(content[27:30], "little"),
            )
        if content[12:16] == b"VP8L" and len(content) >= 25:
            bits = int.from_bytes(content[21:25], "little")
            return _valid_dimensions((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        marker = content.find(b"\x9d\x01\x2a")
        if marker >= 0 and len(content) >= marker + 7:
            return _valid_dimensions(
                int.from_bytes(content[marker + 3 : marker + 5], "little") & 0x3FFF,
                int.from_bytes(content[marker + 5 : marker + 7], "little") & 0x3FFF,
            )
    if extension == ".jpg" and content.startswith(b"\xff\xd8"):
        offset = 2
        while offset + 9 <= len(content):
            if content[offset] != 0xFF:
                offset += 1
                continue
            marker = content[offset + 1]
            offset += 2
            if marker in {0xD8, 0xD9}:
                continue
            if offset + 2 > len(content):
                break
            segment_length = int.from_bytes(content[offset : offset + 2], "big")
            if segment_length < 2 or offset + segment_length > len(content):
                break
            if (
                marker
                in {
                    0xC0,
                    0xC1,
                    0xC2,
                    0xC3,
                    0xC5,
                    0xC6,
                    0xC7,
                    0xC9,
                    0xCA,
                    0xCB,
                    0xCD,
                    0xCE,
                    0xCF,
                }
                and segment_length >= 7
            ):
                return _valid_dimensions(
                    int.from_bytes(content[offset + 5 : offset + 7], "big"),
                    int.from_bytes(content[offset + 3 : offset + 5], "big"),
                )
            offset += segment_length
    return None


def _image_layout(image: DownloadedImage) -> str:
    if image.width and image.height and image.width / image.height >= 1.35:
        return "hero"
    return "side"


async def _async_download_one(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    source_url: str,
) -> tuple[bytes, str]:
    """Download and validate one image through a bounded trusted redirect chain."""

    current_url = source_url
    try:
        async with semaphore:
            for redirect_count in range(3):
                async with session.get(
                    current_url,
                    allow_redirects=False,
                    headers={"User-Agent": "HomeAssistant Free Library Events"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if 300 <= response.status < 400:
                        location = getattr(response, "headers", {}).get("Location", "")
                        redirected_url = clean_image_url(
                            urllib.parse.urljoin(current_url, location)
                        )
                        if not redirected_url or redirect_count == 2:
                            raise _ImageDownloadFailure(
                                "unsafe or excessive image redirect",
                                allow_remote_fallback=False,
                            )
                        current_url = redirected_url
                        continue
                    if response.status >= 500:
                        raise _ImageDownloadFailure(
                            f"HTTP {response.status}", allow_remote_fallback=True
                        )
                    if response.status != 200:
                        raise _ImageDownloadFailure(
                            f"HTTP {response.status}", allow_remote_fallback=False
                        )
                    if (
                        response.content_length is not None
                        and response.content_length > MAX_IMAGE_BYTES
                    ):
                        raise _ImageDownloadFailure(
                            "image exceeds the per-file size limit",
                            allow_remote_fallback=False,
                        )
                    try:
                        content = await response.content.readexactly(
                            MAX_IMAGE_BYTES + 1
                        )
                    except asyncio.IncompleteReadError as err:
                        content = err.partial
                    else:
                        raise _ImageDownloadFailure(
                            "image exceeds the per-file size limit",
                            allow_remote_fallback=False,
                        )
                    break
            else:
                raise _ImageDownloadFailure(
                    "excessive image redirects", allow_remote_fallback=False
                )
    except _ImageDownloadFailure:
        raise
    except (TimeoutError, aiohttp.ClientError) as err:
        raise _ImageDownloadFailure(
            str(err) or type(err).__name__, allow_remote_fallback=True
        ) from err
    extension = _image_extension(content)
    if not extension:
        raise _ImageDownloadFailure(
            "response is not a supported email image",
            allow_remote_fallback=False,
        )
    return content, extension


async def async_download_event_images(
    session: aiohttp.ClientSession,
    events: Sequence[Event],
) -> ImageDownloadBatch:
    """Download a bounded set of unique images used by the selected events."""

    requests = _unique_image_requests(events)
    attempted = requests[:MAX_EMBEDDED_IMAGES]
    semaphore = asyncio.Semaphore(MAX_IMAGE_REQUEST_CONCURRENCY)
    results = await asyncio.gather(
        *(
            _async_download_one(session, semaphore, source_url)
            for source_url, _title in attempted
        ),
        return_exceptions=True,
    )

    images: list[DownloadedImage] = []
    failures: list[str] = []
    fallback_urls: list[str] = []
    total_bytes = 0
    for (source_url, title), result in zip(attempted, results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            failures.append(f"{title}: {result}")
            if (
                isinstance(result, _ImageDownloadFailure)
                and result.allow_remote_fallback
            ):
                fallback_urls.append(source_url)
            continue
        content, extension = result
        if total_bytes + len(content) > MAX_TOTAL_IMAGE_BYTES:
            failures.append(f"{title}: digest image size limit reached")
            fallback_urls.append(source_url)
            continue
        total_bytes += len(content)
        dimensions = _image_dimensions(content, extension)
        images.append(
            DownloadedImage(
                source_url,
                content,
                extension,
                *(dimensions or (None, None)),
            )
        )

    skipped = requests[MAX_EMBEDDED_IMAGES:]
    failures.extend(
        f"{title}: digest image count limit reached" for _url, title in skipped
    )
    fallback_urls.extend(url for url, _title in skipped)
    return ImageDownloadBatch(
        images=tuple(images),
        requested_count=len(requests),
        failure_count=len(failures),
        failure_examples=tuple(failures[:MAX_FAILURE_EXAMPLES]),
        fallback_urls=tuple(fallback_urls),
    )


def store_downloaded_images(
    root_directory: Path,
    batch: ImageDownloadBatch,
) -> StoredImageBundle:
    """Store a download batch in one integration-owned run directory."""

    if not batch.images:
        return StoredImageBundle({}, (), None)

    run_directory = root_directory / f"run-{uuid4().hex}"
    paths: list[str] = []
    source_url_to_cid: dict[str, str] = {}
    source_url_to_layout: dict[str, str] = {}
    try:
        run_directory.mkdir(parents=True)
        (run_directory / _MANAGED_MARKER).write_text(
            datetime.now(UTC).isoformat(), encoding="utf-8"
        )
        for index, image in enumerate(batch.images, start=1):
            filename = f"event-{index:02d}{image.extension}"
            path = run_directory / filename
            path.write_bytes(image.content)
            paths.append(str(path))
            source_url_to_cid[image.source_url] = f"cid:{filename}"
            source_url_to_layout[image.source_url] = _image_layout(image)
    except OSError:
        shutil.rmtree(run_directory, ignore_errors=True)
        raise
    return StoredImageBundle(
        source_url_to_cid,
        tuple(paths),
        run_directory,
        source_url_to_layout,
    )


def remove_stored_image_run(run_directory: Path) -> None:
    """Remove exactly one integration-owned image run."""

    if not _RUN_DIRECTORY_PATTERN.fullmatch(run_directory.name):
        return
    if not (run_directory / _MANAGED_MARKER).is_file():
        return
    shutil.rmtree(run_directory, ignore_errors=True)
    try:
        run_directory.parent.rmdir()
    except OSError:
        pass


def purge_stored_image_runs(root_directory: Path) -> None:
    """Remove every image run previously owned by this integration."""

    if not root_directory.is_dir():
        return
    for candidate in root_directory.iterdir():
        if candidate.is_dir():
            remove_stored_image_run(candidate)
    try:
        root_directory.rmdir()
    except OSError:
        pass


def purge_stale_image_runs(root_directory: Path, cutoff_timestamp: float) -> None:
    """Remove integration-owned image runs created before a cutoff."""

    if not root_directory.is_dir():
        return
    for candidate in root_directory.iterdir():
        marker = candidate / _MANAGED_MARKER
        try:
            is_stale = marker.is_file() and marker.stat().st_mtime < cutoff_timestamp
        except OSError:
            continue
        if is_stale:
            remove_stored_image_run(candidate)
    try:
        root_directory.rmdir()
    except OSError:
        pass
