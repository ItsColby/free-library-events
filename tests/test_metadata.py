"""Static contracts for product metadata and validation configuration."""

from __future__ import annotations

import ast
import json
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components/free_library_events"


def _json_file(path: Path) -> dict[str, object]:
    """Load one product-owned JSON metadata file."""

    return json.loads(path.read_text(encoding="utf-8"))


class HomeAssistantMetadataTests(unittest.TestCase):
    """Keep public metadata and repository validation contracts aligned."""

    def test_tool_gates_are_owned_by_the_documented_runner(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yaml").read_text(
            encoding="utf-8"
        )
        release_runner = (ROOT / "scripts/verify-release-local.sh").read_text(
            encoding="utf-8"
        )
        development = (ROOT / "docs/development.md").read_text(encoding="utf-8")
        commands = (
            "python -m ruff format --check custom_components tests scripts",
            "python -m ruff check custom_components tests scripts",
            "python -m mypy custom_components/free_library_events",
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
        self.assertIn("scripts/verify-release-local.sh", development)
        self.assertIn("scripts/verify-release-local.ps1", development)

        dependabot = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
        self.assertIn("default-days: 7", dependabot)
        self.assertEqual(1, dependabot.count("package-ecosystem: github-actions"))
        self.assertNotIn("package-ecosystem: pip", dependabot)
        self.assertEqual(1, dependabot.count("interval: weekly"))
        self.assertNotIn("interval: daily", dependabot)

    def test_ruff_policy_is_repository_owned_and_high_signal(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        ruff = config["tool"]["ruff"]
        lint = ruff["lint"]

        self.assertTrue(config["tool"]["mypy"]["strict"])
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
        development = (ROOT / "docs/development.md").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/validate.yaml").read_text(
            encoding="utf-8"
        )
        release_runner = (ROOT / "scripts/verify-release-local.sh").read_text(
            encoding="utf-8"
        )
        harness_install = (
            'python -m pip install "pytest-homeassistant-custom-component==0.13.354"'
        )
        current_harness_install = (
            'python -m pip install "pytest-homeassistant-custom-component==0.13.365"'
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
            "Home Assistant current integration tests (Core 2026.9.2)",
            workflow,
        )
        self.assertIn("bash scripts/verify-release-local.sh minimum native", workflow)
        self.assertIn("bash scripts/verify-release-local.sh current native", workflow)
        minimum_job = release_runner.index("run_minimum()")
        current_job = release_runner.index("run_current()")
        release_job = release_runner.index("run_release()")
        minimum_workflow = release_runner[minimum_job:current_job]
        current_workflow = release_runner[current_job:release_job]

        # The isolated runner appends checks after its environment installation.
        def execution_order(block):
            setup = block[block.index("  run_python '") :]
            checks = block[
                block.index("  local checks=") : block.index('  if [[ "$mode"')
            ]
            return setup + checks

        minimum_workflow = execution_order(minimum_workflow)
        current_workflow = execution_order(current_workflow)
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
                "python -m mypy custom_components/free_library_events"
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
            self.assertIn("pytest tests -q", lane)
            self.assertIn("--ignore=tests/test_digest.py", lane)
            self.assertIn("--ignore=tests/test_validation_selection.py", lane)
            for module in ha_tests:
                with self.subTest(module=module):
                    self.assertNotIn(f"--ignore={module}", lane)
        self.assertEqual(
            [
                ROOT / "requirements-ha-current.txt",
                ROOT / "requirements-ha-test.txt",
            ],
            sorted(ROOT.glob("requirements-ha-*.txt")),
        )

        minimum_requirements = (ROOT / "requirements-ha-test.txt").read_text(
            encoding="utf-8"
        )
        current_requirements = (ROOT / "requirements-ha-current.txt").read_text(
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
                "homeassistant==2026.9.2",
                "PyTurboJPEG==1.8.3",
                "ha-ffmpeg==3.2.2",
                "mutagen==1.48.1",
            ],
            current_requirements.splitlines(),
        )
        self.assertIn(dependency_check, development)
        self.assertIn("Core 2026.8.0 with harness 0.13.354", development)
        self.assertIn("Core 2026.9.1 with harness 0.13.364", development)
        self.assertEqual(
            "2026.8.0",
            _json_file(ROOT / "hacs.json")["homeassistant"],
        )

    def translation_keys(self, source: str, exception_types: set[str]) -> set[str]:
        keys: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if not (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id in exception_types
            ):
                continue
            self.assertEqual([], node.exc.args)
            keyword_values = {item.arg: item.value for item in node.exc.keywords}
            self.assertIn("translation_domain", keyword_values)
            translation_key = keyword_values.get("translation_key")
            self.assertIsInstance(translation_key, ast.Constant)
            self.assertIsInstance(translation_key.value, str)
            keys.add(translation_key.value)
        return keys

    def test_user_visible_action_exceptions_are_translated(self) -> None:
        init_text = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        strings = _json_file(INTEGRATION / "translations/en.json")
        exception_keys = self.translation_keys(
            init_text, {"HomeAssistantError", "ServiceValidationError"}
        )
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
        coordinator_text = (INTEGRATION / "coordinator.py").read_text(encoding="utf-8")
        strings = _json_file(INTEGRATION / "translations/en.json")
        translated_failures = self.translation_keys(coordinator_text, {"UpdateFailed"})
        self.assertIn("library_source_update_failed", translated_failures)
        self.assertTrue(translated_failures <= set(strings["exceptions"]))

    def test_service_metadata_has_translations_and_current_icons(self) -> None:
        services_text = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
        translations = _json_file(INTEGRATION / "translations/en.json")
        icons = _json_file(INTEGRATION / "icons.json")
        service_matches = list(
            re.finditer(r"^([a-z_]+):$", services_text, re.MULTILINE)
        )
        service_keys = {match.group(1) for match in service_matches}

        self.assertEqual(service_keys, set(translations["services"]))
        self.assertEqual(service_keys, set(icons["services"]))
        for index, match in enumerate(service_matches):
            key = match.group(1)
            block_end = (
                service_matches[index + 1].start()
                if index + 1 < len(service_matches)
                else len(services_text)
            )
            service_block = services_text[match.end() : block_end]
            field_keys = set(
                re.findall(r"^    ([a-z_]+):$", service_block, re.MULTILINE)
            )
            translated = translations["services"][key]
            self.assertIn("name", translated)
            self.assertIn("description", translated)
            self.assertEqual(field_keys, set(translated["fields"]))
            for field in translated["fields"].values():
                self.assertIn("name", field)
                self.assertIn("description", field)
            self.assertEqual({"service"}, set(icons["services"][key]))
            self.assertRegex(icons["services"][key]["service"], r"^mdi:[a-z0-9-]+$")

    def test_entity_translation_keys_have_current_icons(self) -> None:
        translations = _json_file(INTEGRATION / "translations/en.json")
        icons = _json_file(INTEGRATION / "icons.json")
        expected = {
            "button": {"refresh_events"},
            "calendar": {"events"},
            "sensor": {"status"},
        }

        for platform, keys in expected.items():
            with self.subTest(platform=platform):
                self.assertEqual(keys, set(translations["entity"][platform]))
                self.assertEqual(keys, set(icons["entity"][platform]))

    def test_status_sensor_owns_a_complete_translated_enum(self) -> None:
        translations = _json_file(INTEGRATION / "translations/en.json")
        sensor_text = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
        expected_states = {"ok", "limited", "partial", "error"}

        self.assertEqual(
            expected_states,
            set(translations["entity"]["sensor"]["status"]["state"]),
        )
        self.assertIn("SensorDeviceClass.ENUM", sensor_text)
        for state in expected_states:
            self.assertIn(f'"{state}"', sensor_text)

    def test_every_integration_json_file_is_valid(self) -> None:
        paths = [*INTEGRATION.rglob("*.json"), ROOT / "hacs.json"]
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsInstance(_json_file(path), dict)

    def test_maintained_text_has_no_trailing_whitespace(self) -> None:
        suffixes = {".json", ".md", ".py", ".ps1", ".sh", ".txt", ".yaml", ".yml"}
        paths = [
            path
            for name in ("custom_components", "tests", ".github", "scripts", "docs")
            for path in (ROOT / name).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in suffixes
        ]
        paths.extend(
            ROOT / name
            for name in (
                "LICENSE",
                "README.md",
                "RELEASE_NOTES.md",
                "hacs.json",
                "pyproject.toml",
                "requirements-ha-test.txt",
                "requirements-ha-current.txt",
                ".gitattributes",
                ".gitignore",
            )
        )
        failures = [
            f"{path.relative_to(ROOT)}:{line}"
            for path in paths
            for line, text in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            )
            if text.endswith((" ", "\t"))
        ]
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()
