"""Tests for the public repository safety guard."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_public_safety import (
    PublicSafetyError,
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

    def test_local_hostname_detection_preserves_embedded_suffix_semantics(self) -> None:
        self.assertIn(
            "local hostname",
            _text_failures("router" + ".local.example"),
        )
        self.assertIn(
            "local hostname",
            _text_failures("router" + ".local..example"),
        )
        self.assertNotIn(
            "local hostname",
            _text_failures("local" + ".example"),
        )

    def test_public_examples_and_github_noreply_are_allowed(self) -> None:
        text = (
            "person@example.com person@example.test "
            "1361774+ItsColby@users.noreply.github.com noreply@github.com"
        )
        self.assertEqual(set(), _text_failures(text))

    def test_email_detection_preserves_sentence_punctuation(self) -> None:
        self.assertIn(
            "non-example email address",
            _text_failures("Contact person" + "@real-domain.dev."),
        )
        self.assertIn(
            "non-example email address",
            _text_failures("Contact person" + "@real-domain.dev-suffix"),
        )
        self.assertEqual(set(), _text_failures("Contact person@example.com."))
        self.assertEqual(set(), _text_failures("Contact .noreply@github.com"))

    def test_email_detection_rejects_malformed_domain_prefix(self) -> None:
        self.assertNotIn(
            "non-example email address",
            _text_failures("Malformed @" + ".cX"),
        )

    def test_guard_scans_tracked_and_untracked_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Safe public text.\n", encoding="utf-8")
            file_count, failures = run_guard(root)
        self.assertEqual(1, file_count)
        self.assertEqual([], failures)

    def test_guard_scans_git_tracked_and_untracked_but_not_ignored_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (root / "tracked.txt").write_text("Safe public text.\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            private = "person" + "@real-domain.dev"
            (root / "untracked.txt").write_text(private, encoding="utf-8")
            (root / "ignored.txt").write_text(private, encoding="utf-8")
            file_count, failures = run_guard(root)
        self.assertEqual(3, file_count)
        self.assertEqual(["untracked.txt: non-example email address"], failures)

    def test_guard_rejects_failed_git_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            commands = [
                subprocess.CompletedProcess([], 0, str(root).encode() + b"\n", b""),
                subprocess.CompletedProcess([], 128, b"", b"inventory failed"),
            ]
            with (
                patch(
                    "scripts.check_public_safety.subprocess.run", side_effect=commands
                ),
                self.assertRaisesRegex(PublicSafetyError, "inventory repository"),
            ):
                run_guard(root)

    def test_guard_rejects_unavailable_git_in_checkout(self) -> None:
        for result in (
            FileNotFoundError("git unavailable"),
            subprocess.CompletedProcess([], 128, b"", b"invalid checkout"),
        ):
            with (
                self.subTest(result=result),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / ".git").mkdir()
                kwargs = (
                    {"side_effect": result}
                    if isinstance(result, FileNotFoundError)
                    else {"return_value": result}
                )
                with (
                    patch("scripts.check_public_safety.subprocess.run", **kwargs),
                    self.assertRaises(PublicSafetyError),
                ):
                    run_guard(root)

    def test_guard_scans_archive_without_git_or_under_generated_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "build" / "source"
            root.mkdir(parents=True)
            (root / "README.md").write_text("Safe public text.\n", encoding="utf-8")
            with patch(
                "scripts.check_public_safety.subprocess.run",
                side_effect=FileNotFoundError,
            ):
                self.assertEqual((1, []), run_guard(root))

    def test_guard_rejects_missing_root(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(PublicSafetyError, "existing directory"),
        ):
            run_guard(Path(directory) / "missing")

    def test_guard_rejects_link_candidates_without_reading_their_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            linked = root / "linked.txt"
            with (
                patch(
                    "scripts.check_public_safety._candidate_files",
                    return_value=[linked],
                ),
                patch.object(Path, "is_symlink", return_value=True),
                patch.object(Path, "read_bytes") as read_bytes,
            ):
                file_count, failures = run_guard(root)
            read_bytes.assert_not_called()
        self.assertEqual(1, file_count)
        self.assertEqual(["linked.txt: unreviewed symbolic link or junction"], failures)

    def test_guard_rejects_sensitive_file_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filename = "person" + "@real-domain.dev"
            (root / filename).write_text("Safe public text.\n", encoding="utf-8")
            file_count, failures = run_guard(root)
        self.assertEqual(1, file_count)
        self.assertEqual(
            [f"{filename}: non-example email address in file name"], failures
        )

    def test_guard_scans_text_without_a_file_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gitignore").write_text("Safe public text.\n", encoding="utf-8")
            file_count, failures = run_guard(root)
        self.assertEqual(1, file_count)
        self.assertEqual([], failures)

    def test_guard_rejects_unreviewed_binary_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00private")
            file_count, failures = run_guard(root)
        self.assertEqual(1, file_count)
        self.assertEqual(["image.png: unreviewed binary content"], failures)

    def test_guard_requires_the_reviewed_binary_hash_at_the_exact_path(self) -> None:
        content = b"\0reviewed image"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "image.png"
            image_path.write_bytes(content)
            with patch.dict(
                "scripts.check_public_safety.REVIEWED_BINARY_SHA256",
                {"image.png": hashlib.sha256(content).hexdigest()},
                clear=True,
            ):
                self.assertEqual((1, []), run_guard(root))
                image_path.write_bytes(content + b"changed")
                self.assertEqual(
                    (1, ["image.png: unreviewed binary content"]), run_guard(root)
                )

    def test_guard_propagates_inventory_and_file_access_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Safe public text.\n", encoding="utf-8")
            with (
                patch(
                    "scripts.check_public_safety._path_present",
                    side_effect=PermissionError,
                ),
                self.assertRaises(PermissionError),
            ):
                run_guard(root)
            with (
                patch.object(Path, "read_bytes", side_effect=PermissionError),
                self.assertRaises(PermissionError),
            ):
                run_guard(root)
            with (
                patch(
                    "scripts.check_public_safety.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("git", 30),
                ),
                self.assertRaises(subprocess.TimeoutExpired),
            ):
                run_guard(root)

    def test_guard_ignores_generated_cache_directories_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("Safe public text.\n", encoding="utf-8")
            cache = root / ".ruff_cache"
            cache.mkdir()
            (cache / "cache.bin").write_bytes(b"\x00generated")
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
