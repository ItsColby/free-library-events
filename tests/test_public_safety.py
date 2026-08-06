"""Tests for the public repository safety guard."""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts.check_public_safety import (
    _text_failures,
    run_guard,
)


class PublicSafetyGuardTests(unittest.TestCase):
    def test_latest_ruff_and_strict_mypy_are_documented(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/validate.yaml").read_text(
            encoding="utf-8"
        )
        readme = (root / "README.md").read_text(encoding="utf-8")
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        commands = (
            "python -m ruff format --check custom_components tests scripts",
            "python -m ruff check custom_components tests scripts",
            "python -m mypy --strict custom_components/free_library_events",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertIn(command, workflow)
                self.assertIn(command, readme)
                self.assertIn(command, agents)

        self.assertIn(
            "python -m pip install --upgrade ruff shellcheck-py zizmor", workflow
        )
        self.assertIn("python -m pip install --upgrade mypy", workflow)
        self.assertIn(
            "go install github.com/rhysd/actionlint/cmd/actionlint@latest",
            workflow,
        )
        self.assertIn("actionlint -version", workflow)
        self.assertIn("shellcheck --version", workflow)
        self.assertIn("run: actionlint", workflow)
        self.assertIn("zizmor --persona auditor .", workflow)
        self.assertIn("zizmor --persona auditor .", readme)
        self.assertIn("python -m mypy --version", workflow)
        self.assertIn(
            "python -m pip install --upgrade ruff mypy shellcheck-py zizmor", readme
        )
        self.assertIn(
            "python -m pip install --upgrade ruff mypy shellcheck-py zizmor", agents
        )
        self.assertNotIn("ruff==", workflow)
        self.assertNotIn("shellcheck-py==", workflow)

        dependabot = (root / ".github/dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("default-days: 7", dependabot)

    def test_ruff_policy_is_repository_owned_and_high_signal(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        ruff = config["tool"]["ruff"]
        lint = ruff["lint"]

        self.assertEqual("py314", ruff["target-version"])
        self.assertNotIn("required-version", ruff)
        self.assertEqual(17, lint["mccabe"]["max-complexity"])
        self.assertTrue(
            {
                "ASYNC",
                "B",
                "BLE",
                "C4",
                "C901",
                "DTZ",
                "LOG",
                "N818",
                "PERF",
                "PLC",
                "PLE",
                "PLW",
                "RUF",
                "S104",
                "S113",
                "S310",
                "S314",
                "S324",
                "S501",
                "S506",
                "S507",
                "TID",
            }
            <= set(lint["extend-select"])
        )
        self.assertTrue({"RUF001", "RUF002", "RUF003"}.isdisjoint(lint["ignore"]))
        self.assertEqual(["T20"], lint["per-file-ignores"]["scripts/**"])

    def test_home_assistant_harness_and_core_install_in_separate_steps(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/validate.yaml").read_text(
            encoding="utf-8"
        )
        harness_install = (
            'python -m pip install "pytest-homeassistant-custom-component=='
            '$HARNESS_VERSION"'
        )
        requirements_install = 'python -m pip install --upgrade -r "$REQUIREMENTS_FILE"'

        self.assertIn("harness: 0.13.345", workflow)
        self.assertIn("harness: 0.13.354", workflow)
        self.assertIn("HARNESS_VERSION: ${{ matrix.harness }}", workflow)
        self.assertIn("REQUIREMENTS_FILE: ${{ matrix.requirements }}", workflow)
        self.assertIn(harness_install, workflow)
        self.assertIn(requirements_install, workflow)
        self.assertLess(
            workflow.index(harness_install), workflow.index(requirements_install)
        )
        for requirements in (
            "requirements-ha-test.txt",
            "requirements-ha-test-current.txt",
        ):
            self.assertNotIn(
                "pytest-homeassistant-custom-component",
                (root / requirements).read_text(encoding="utf-8"),
            )

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
