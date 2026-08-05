"""Tests for the public repository safety guard."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.check_public_safety import (
    _text_failures,
    run_guard,
)


class PublicSafetyGuardTests(unittest.TestCase):
    def test_user_visible_action_exceptions_are_translated(self) -> None:
        root = Path(__file__).resolve().parents[1]
        init_text = (
            root / "custom_components/free_library_events/__init__.py"
        ).read_text(encoding="utf-8")
        strings = json.loads(
            (
                root / "custom_components/free_library_events/translations/en.json"
            ).read_text(encoding="utf-8")
        )

        exception_keys: set[str] = set()
        for node in ast.walk(ast.parse(init_text)):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            if not (
                isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id in {"HomeAssistantError", "ServiceValidationError"}
            ):
                continue
            self.assertEqual([], node.exc.args)
            keyword_values = {item.arg: item.value for item in node.exc.keywords}
            self.assertIn("translation_domain", keyword_values)
            translation_key = keyword_values.get("translation_key")
            self.assertIsInstance(translation_key, ast.Constant)
            self.assertIsInstance(translation_key.value, str)
            exception_keys.add(translation_key.value)

        self.assertEqual(
            {
                "library_data_unavailable",
                "library_refresh_failed",
                "single_loaded_entry_required",
            },
            exception_keys,
        )
        self.assertTrue(exception_keys <= set(strings["exceptions"]))

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
                self.assertIn(expected, _text_failures(sample))

    def test_all_rfc1918_address_ranges_are_rejected(self) -> None:
        samples = (
            "10" + ".1.2.3",
            "172" + ".16.1.2",
            "172" + ".31.1.2",
            "192" + ".168.1.2",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertIn("private IPv4 address", _text_failures(sample))

    def test_local_hostname_check_handles_many_labels_without_backtracking(
        self,
    ) -> None:
        sample = (("segment" + ".") * 10_000) + "local"
        self.assertIn("local hostname", _text_failures(sample))

    def test_public_examples_and_github_noreply_are_allowed(self) -> None:
        text = " ".join(
            (
                "person@example.com",
                "person@example.test",
                "1361774+ItsColby@users.noreply.github.com",
                "noreply@github.com",
            )
        )
        self.assertEqual(set(), _text_failures(text))

    def test_guard_scans_tracked_and_untracked_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Safe public text.\n", encoding="utf-8")
            file_count, failures = run_guard(root)
        self.assertEqual(1, file_count)
        self.assertEqual([], failures)

    def test_guard_scans_tree_nested_inside_parent_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            subprocess.run(
                ["git", "init", "--quiet", str(parent)],
                check=True,
            )
            root = parent / "extracted-tree"
            root.mkdir()
            (root / "README.md").write_text("Safe public text.\n", encoding="utf-8")
            file_count, failures = run_guard(root)
        self.assertEqual(1, file_count)
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
