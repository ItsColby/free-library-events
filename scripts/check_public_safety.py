"""Reject public repository content that resembles private data or secrets."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EMAILS = {"noreply@github.com"}
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "example.test",
    "users.noreply.github.com",
}
REVIEWED_BINARY_SHA256 = {
    "custom_components/free_library_events/brand/icon.png": (
        "e8b9da34a92b5472a485c9cd172204e6f8fcf95426157e0eb6ed5bc42e4bf9f3"
    ),
}
IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".local",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "venv",
}

HOSTNAME_TOKEN_RE = re.compile(r"[A-Z0-9_.-]+", re.IGNORECASE)
LOCAL_HOSTNAME_SUFFIXES = {"home", "lan", "local"}
EMAIL_LOCAL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-"
)
EMAIL_DOMAIN_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
)
PUBLIC_SAFETY_PATTERNS = (
    (
        "absolute Windows path",
        re.compile(r"(?<![A-Z0-9])[A-Z]:[\\/]", re.IGNORECASE),
    ),
    (
        "local user path",
        re.compile(r"(?i)(?:\x2fhome\x2f[^/\s]+\x2f|\x2fUsers\x2f[^/\s]+\x2f)"),
    ),
    (
        "private IPv4 address",
        re.compile(
            r"(?<!\d)(?:"
            r"10\.(?:\d{1,3}\.){2}\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3}|"
            r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
            r")(?!\d)"
        ),
    ),
    (
        "private key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "GitHub token",
        re.compile(
            r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|"
            r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"
        ),
    ),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
)


def _contains_local_hostname(text: str) -> bool:
    """Return whether text contains a dotted local hostname in linear time."""

    for match in HOSTNAME_TOKEN_RE.finditer(text):
        prior_label_count = 0
        for label in match.group(0).casefold().split("."):
            if not _valid_hostname_label(label):
                prior_label_count = 0
                continue
            if prior_label_count and label in LOCAL_HOSTNAME_SUFFIXES:
                return True
            prior_label_count += 1
    return False


def _valid_hostname_label(label: str) -> bool:
    return bool(label) and all(char.isalnum() or char in "-_" for char in label)


def _email_addresses(text: str) -> Iterator[tuple[str, str]]:
    """Yield regex-compatible email and domain pairs without backtracking."""

    search_from = 0
    while (at_index := text.find("@", search_from)) >= 0:
        local_run_start = at_index
        while local_run_start > 0 and text[local_run_start - 1] in EMAIL_LOCAL_CHARS:
            local_run_start -= 1
        local_start = next(
            (
                index
                for index in range(local_run_start, at_index)
                if _is_word_boundary(text, index)
            ),
            None,
        )

        domain_start = at_index + 1
        domain_run_end = domain_start
        while domain_run_end < len(text) and text[domain_run_end] in EMAIL_DOMAIN_CHARS:
            domain_run_end += 1

        valid_end: int | None = None
        last_dot = -1
        top_level_length = 0
        top_level_is_alpha = False
        for index in range(domain_start, domain_run_end):
            char = text[index]
            if char == ".":
                last_dot = index
                top_level_length = 0
                top_level_is_alpha = True
            elif last_dot >= 0:
                top_level_length += 1
                top_level_is_alpha = top_level_is_alpha and char.isalpha()
            if (
                last_dot > domain_start
                and top_level_is_alpha
                and top_level_length >= 2
                and _is_word_boundary(text, index + 1)
            ):
                valid_end = index + 1

        if local_start is not None and valid_end is not None:
            domain = text[domain_start:valid_end]
            yield f"{text[local_start:at_index]}@{domain}", domain
        search_from = at_index + 1


def _is_word_boundary(text: str, index: int) -> bool:
    left_is_word = index > 0 and _is_word_char(text[index - 1])
    right_is_word = index < len(text) and _is_word_char(text[index])
    return left_is_word != right_is_word


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


class PublicSafetyError(ValueError):
    """Raised when repository content cannot be inventoried safely."""


def _raise_walk_error(error: OSError) -> None:
    raise error


def _archive_files(root: Path) -> list[Path]:
    """Inventory source archives without traversing generated directories."""

    paths = []
    for directory, directory_names, filenames in root.walk(on_error=_raise_walk_error):
        descend_into = []
        for name in directory_names:
            if name in IGNORED_DIRECTORY_NAMES or name.endswith(".egg-info"):
                continue
            candidate = directory / name
            if candidate.is_junction():
                paths.append(candidate)
            else:
                descend_into.append(name)
        directory_names[:] = descend_into
        paths.extend(directory / name for name in filenames)
    return paths


def _path_present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _candidate_files(root: Path = ROOT) -> list[Path]:
    if not root.is_dir():
        raise PublicSafetyError("source root must be an existing directory")
    git_marker = root / ".git"
    has_git_marker = _path_present(git_marker)
    try:
        top_level = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except FileNotFoundError:
        if has_git_marker:
            raise PublicSafetyError(
                "Git is required to inventory this checkout"
            ) from None
        return sorted(_archive_files(root))

    is_repository_root = (
        top_level.returncode == 0
        and Path(os.fsdecode(top_level.stdout).strip()).resolve() == root.resolve()
    )
    if not is_repository_root:
        if has_git_marker:
            raise PublicSafetyError("Git could not identify the checkout root")
        return sorted(_archive_files(root))

    tracked = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if tracked.returncode != 0:
        raise PublicSafetyError("Git could not inventory repository files")
    paths = {root / os.fsdecode(raw) for raw in tracked.stdout.split(b"\0") if raw}
    # Cached entries deleted from the current source tree are no longer content.
    return sorted(path for path in paths if _path_present(path))


def _text_failures(text: str) -> set[str]:
    failures = {
        label for label, pattern in PUBLIC_SAFETY_PATTERNS if pattern.search(text)
    }
    if _contains_local_hostname(text):
        failures.add("local hostname")
    for raw_address, raw_domain in _email_addresses(text):
        address = raw_address.casefold()
        domain = raw_domain.casefold()
        if address not in ALLOWED_EMAILS and domain not in ALLOWED_EMAIL_DOMAINS:
            failures.add("non-example email address")
    return failures


def run_guard(root: Path = ROOT) -> tuple[int, list[str]]:
    root = root.resolve()
    files = _candidate_files(root)
    failures: set[str] = set()
    for path in files:
        relative = path.relative_to(root)
        relative_posix = relative.as_posix()
        for label in _text_failures(relative_posix):
            failures.add(f"{relative}: {label} in file name")
        if any(
            candidate.is_symlink() or candidate.is_junction()
            for candidate in (path, *path.parents)
            if candidate != root and root in candidate.parents
        ):
            failures.add(f"{relative}: unreviewed symbolic link or junction")
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            failures.add(f"{relative}: unsupported file type")
            continue
        raw = path.read_bytes()
        is_binary = b"\0" in raw
        try:
            text = "" if is_binary else raw.decode("utf-8")
        except UnicodeDecodeError:
            is_binary = True

        if is_binary:
            expected_hash = REVIEWED_BINARY_SHA256.get(relative_posix)
            if expected_hash != hashlib.sha256(raw).hexdigest():
                failures.add(f"{relative}: unreviewed binary content")
            continue

        for label in _text_failures(text):
            failures.add(f"{relative}: {label}")
    return len(files), sorted(failures)


def main() -> int:
    try:
        file_count, failures = run_guard()
    except (PublicSafetyError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Public safety guard could not complete: {exc}", file=sys.stderr)
        return 1
    if failures:
        raise SystemExit("Public safety guard failed:\n" + "\n".join(failures))
    print(f"Public safety guard passed for {file_count} repository files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
