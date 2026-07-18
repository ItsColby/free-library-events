"""Tests for the public repository safety guard."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_public_safety import (
    PRIVATE_DENYLIST_ENV,
    _private_denylist,
    _text_failures,
    run_guard,
)


class PublicSafetyGuardTests(unittest.TestCase):
    def test_generic_patterns_reject_sensitive_shapes(self) -> None:
        samples = {
            "absolute Windows path": "C:" + r"\Users\Example\file.txt",
            "local user path": "/home/" + "example/private.txt",
            "local hostname": "router" + ".local",
            "non-example email address": "person" + "@real-domain.dev",
            "GitHub token": "ghp_" + ("a" * 36),
        }
        for expected, sample in samples.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, _text_failures(sample, ()))

    def test_all_rfc1918_address_ranges_are_rejected(self) -> None:
        samples = (
            "10" + ".1.2.3",
            "172" + ".16.1.2",
            "172" + ".31.1.2",
            "192" + ".168.1.2",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertIn("private IPv4 address", _text_failures(sample, ()))

    def test_public_examples_and_github_noreply_are_allowed(self) -> None:
        text = " ".join(
            (
                "person@example.com",
                "person@example.test",
                "1361774+ItsColby@users.noreply.github.com",
                "noreply@github.com",
            )
        )
        self.assertEqual(set(), _text_failures(text, ()))

    def test_private_denylist_is_supplied_outside_the_repository(self) -> None:
        private_value = "Private" + " Fixture"
        with patch.dict(
            os.environ,
            {PRIVATE_DENYLIST_ENV: json.dumps([private_value])},
            clear=True,
        ):
            denylist = _private_denylist(require=True)
        self.assertIn("private denylist match", _text_failures(private_value, denylist))

    def test_required_private_denylist_fails_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                _private_denylist(require=True)

    def test_guard_scans_tracked_and_untracked_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Safe public text.\n", encoding="utf-8")
            file_count, failures = run_guard(root)
        self.assertEqual(1, file_count)
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
