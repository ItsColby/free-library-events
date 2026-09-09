"""Tests for the public repository safety guard."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_public_safety import (
    PublicSafetyError,
    _text_failures,
    run_guard,
)


class PublicSafetyGuardTests(unittest.TestCase):
    def test_tool_gates_are_owned_by_the_documented_runner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/validate.yaml").read_text(
            encoding="utf-8"
        )
        release_runner = (root / "scripts/verify-release-local.sh").read_text(
            encoding="utf-8"
        )
        readme = (root / "README.md").read_text(encoding="utf-8")
        commands = (
            "python -m ruff format --check custom_components tests scripts",
            "python -m ruff check custom_components tests scripts",
            "python -m mypy --strict custom_components/free_library_events",
        )

        for command in commands:
            with self.subTest(command=command):
                self.assertIn(command, release_runner)

        self.assertIn(
            'python -m pip install "ruff==0.16.2" "shellcheck-py==0.11.0.1" "zizmor==1.29.0"',
            release_runner,
        )
        self.assertIn('python -m pip install "mypy==2.3.0"', release_runner)
        self.assertIn(
            "go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12",
            release_runner,
        )
        self.assertIn("run_actionlint", release_runner)
        self.assertIn("bash scripts/verify-release-local.sh unit native", workflow)
        self.assertNotIn("ubuntu-latest", workflow)
        self.assertEqual(6, workflow.count("runs-on: ubuntu-24.04"))
        self.assertEqual(1, workflow.count("permissions:"))
        permissions = workflow.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual("  contents: read", permissions)
        self.assertNotIn("GH_TOKEN", release_runner)
        self.assertIn("scripts/verify-release-local.sh", readme)
        self.assertIn("scripts/verify-release-local.ps1", readme)

        dependabot = (root / ".github/dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("default-days: 7", dependabot)
        self.assertEqual(1, dependabot.count("package-ecosystem: github-actions"))
        self.assertNotIn("package-ecosystem: pip", dependabot)
        self.assertEqual(1, dependabot.count("interval: weekly"))
        self.assertNotIn("interval: daily", dependabot)

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

    def test_home_assistant_support_contract_has_minimum_and_current_lanes(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        workflow = (root / ".github/workflows/validate.yaml").read_text(
            encoding="utf-8"
        )
        release_runner = (root / "scripts/verify-release-local.sh").read_text(
            encoding="utf-8"
        )
        harness_install = (
            'python -m pip install "pytest-homeassistant-custom-component==0.13.354"'
        )
        current_harness_install = (
            'python -m pip install "pytest-homeassistant-custom-component==0.13.364"'
        )
        minimum_install = "python -m pip install --upgrade -r requirements-ha-test.txt"
        current_install = (
            "python -m pip install --upgrade -r requirements-ha-current.txt"
        )
        compatibility_check = (
            "python scripts/check_ha_patch_compatibility.py --minimum "
            "requirements-ha-test.txt --current requirements-ha-current.txt"
        )
        dependency_check = "python -m pip check"

        self.assertIn(
            "Home Assistant minimum integration tests (Core 2026.8.0)", workflow
        )
        self.assertIn(
            "Home Assistant current integration tests (Core 2026.9.1)",
            workflow,
        )
        self.assertIn("bash scripts/verify-release-local.sh minimum native", workflow)
        self.assertIn("bash scripts/verify-release-local.sh current native", workflow)
        minimum_job = release_runner.index("run_minimum()")
        current_job = release_runner.index("run_current()")
        release_job = release_runner.index("run_release()")
        minimum_workflow = release_runner[minimum_job:current_job]
        current_workflow = release_runner[current_job:release_job]
        self.assertIn(harness_install, minimum_workflow)
        self.assertIn(minimum_install, minimum_workflow)
        self.assertLess(
            minimum_workflow.index(harness_install),
            minimum_workflow.index(minimum_install),
        )
        self.assertIn(dependency_check, minimum_workflow)
        self.assertLess(
            minimum_workflow.index(minimum_install),
            minimum_workflow.index(dependency_check),
        )
        self.assertLess(
            minimum_workflow.index(dependency_check),
            minimum_workflow.index(
                "python -m mypy --strict custom_components/free_library_events"
            ),
        )
        self.assertIn(current_harness_install, current_workflow)
        self.assertIn(current_install, current_workflow)
        self.assertIn(compatibility_check, current_workflow)
        self.assertLess(
            current_workflow.index(current_harness_install),
            current_workflow.index(current_install),
        )
        self.assertLess(
            current_workflow.index(current_install),
            current_workflow.index(compatibility_check),
        )
        ha_tests = (
            "tests/test_integration_ha.py",
            "tests/test_email_images.py",
            "tests/test_acquisition_ha.py",
        )
        for lane in (minimum_workflow, current_workflow):
            for module in ha_tests:
                with self.subTest(module=module):
                    self.assertIn(module, lane)
        self.assertEqual(
            [
                root / "requirements-ha-current.txt",
                root / "requirements-ha-test.txt",
            ],
            sorted(root.glob("requirements-ha-*.txt")),
        )

        minimum_requirements = (root / "requirements-ha-test.txt").read_text(
            encoding="utf-8"
        )
        current_requirements = (root / "requirements-ha-current.txt").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            [
                "homeassistant==2026.8.0",
                "PyTurboJPEG==1.8.3",
                "ha-ffmpeg==3.2.2",
                "mutagen==1.48.1",
            ],
            minimum_requirements.splitlines(),
        )
        self.assertEqual(
            [
                "homeassistant==2026.9.1",
                "PyTurboJPEG==1.8.3",
                "ha-ffmpeg==3.2.2",
                "mutagen==1.48.1",
            ],
            current_requirements.splitlines(),
        )
        self.assertIn(dependency_check, readme)
        self.assertIn("Core 2026.8.0 with harness 0.13.354", readme)
        self.assertIn("Core 2026.9.1 with harness 0.13.364", readme)
        self.assertEqual(
            "2026.8.0",
            json.loads((root / "hacs.json").read_text(encoding="utf-8"))[
                "homeassistant"
            ],
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
                "settings_changed_during_render",
                "single_loaded_entry_required",
            },
            exception_keys,
        )
        self.assertTrue(exception_keys <= set(strings["exceptions"]))

    def test_coordinator_failures_are_translated(self) -> None:
        root = Path(__file__).resolve().parents[1]
        coordinator_text = (
            root / "custom_components/free_library_events/coordinator.py"
        ).read_text(encoding="utf-8")
        strings = json.loads(
            (
                root / "custom_components/free_library_events/translations/en.json"
            ).read_text(encoding="utf-8")
        )
        translated_failures = []
        for node in ast.walk(ast.parse(coordinator_text)):
            if not (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "UpdateFailed"
            ):
                continue
            self.assertEqual([], node.exc.args)
            keyword_values = {item.arg: item.value for item in node.exc.keywords}
            self.assertIn("translation_domain", keyword_values)
            translation_key = keyword_values.get("translation_key")
            self.assertIsInstance(translation_key, ast.Constant)
            self.assertIsInstance(translation_key.value, str)
            translated_failures.append(translation_key.value)

        self.assertIn("library_source_update_failed", translated_failures)
        self.assertTrue(set(translated_failures) <= set(strings["exceptions"]))

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
