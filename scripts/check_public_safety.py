"""Reject public repository content that resembles private data or secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".svg",
    ".toml",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"LICENSE", "MANIFEST.in"}
PRIVATE_DENYLIST_ENV = "PUBLIC_PRIVACY_DENYLIST_JSON"
ALLOWED_EMAILS = {"noreply@github.com"}
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "example.test",
    "users.noreply.github.com",
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
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
        "local hostname",
        re.compile(
            r"(?i)(?:[a-z0-9_-]+\x2e)+(?:home|lan|local)(?![a-z0-9_-])"
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


def _is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_FILENAMES


def _candidate_files(root: Path = ROOT) -> list[Path]:
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
    )
    if tracked.returncode == 0:
        paths = [
            root / raw.decode("utf-8") for raw in tracked.stdout.split(b"\0") if raw
        ]
    else:
        paths = [
            path
            for path in root.rglob("*")
            if not {".git", ".local", ".venv", "__pycache__"}.intersection(path.parts)
        ]

    return sorted(
        path
        for path in paths
        if path.is_file() and not path.is_symlink() and _is_text_candidate(path)
    )


def _private_denylist(require: bool) -> tuple[str, ...]:
    raw = os.environ.get(PRIVATE_DENYLIST_ENV, "")
    if not raw:
        if require:
            raise SystemExit(
                f"{PRIVATE_DENYLIST_ENV} is required for trusted publication checks."
            )
        return ()

    try:
        values = json.loads(raw)
    except json.JSONDecodeError as err:
        raise SystemExit(f"{PRIVATE_DENYLIST_ENV} must contain valid JSON.") from err
    if not isinstance(values, list) or not values:
        raise SystemExit(f"{PRIVATE_DENYLIST_ENV} must be a non-empty JSON list.")
    if any(not isinstance(value, str) or len(value.strip()) < 4 for value in values):
        raise SystemExit(
            f"{PRIVATE_DENYLIST_ENV} entries must be strings of at least 4 characters."
        )
    return tuple(dict.fromkeys(value.casefold() for value in values))


def _text_failures(text: str, private_denylist: tuple[str, ...]) -> set[str]:
    failures = {
        label for label, pattern in PUBLIC_SAFETY_PATTERNS if pattern.search(text)
    }
    for match in EMAIL_RE.finditer(text):
        address = match.group(0).casefold()
        domain = match.group(1).casefold()
        if address not in ALLOWED_EMAILS and domain not in ALLOWED_EMAIL_DOMAINS:
            failures.add("non-example email address")
    folded = text.casefold()
    if any(literal in folded for literal in private_denylist):
        failures.add("private denylist match")
    return failures


def run_guard(
    root: Path = ROOT, *, require_private_denylist: bool = False
) -> tuple[int, list[str]]:
    private_denylist = _private_denylist(require_private_denylist)
    files = _candidate_files(root)
    failures: set[str] = set()
    for path in files:
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.add(f"{relative}: invalid UTF-8 text")
            continue
        for label in _text_failures(text, private_denylist):
            failures.add(f"{relative}: {label}")
    return len(files), sorted(failures)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-private-denylist", action="store_true")
    args = parser.parse_args()
    file_count, failures = run_guard(
        require_private_denylist=args.require_private_denylist
    )
    if failures:
        raise SystemExit("Public safety guard failed:\n" + "\n".join(failures))
    print(f"Public safety guard passed for {file_count} text files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
