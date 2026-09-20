"""Static contracts for product metadata and validation configuration."""

from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

from scripts.check_ha_patch_compatibility import exact_core_pin, stable_version

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components/free_library_events"


def _json_file(path: Path) -> dict[str, object]:
    """Load one product-owned JSON metadata file."""

    return json.loads(path.read_text(encoding="utf-8"))


class HomeAssistantMetadataTests(unittest.TestCase):
    """Keep public metadata and repository validation contracts aligned."""

    def test_ci_uses_read_only_permissions_without_token_injection(self) -> None:
        workflow = (ROOT / ".github/workflows/validate.yaml").read_text(
            encoding="utf-8"
        )
        release_runner = (ROOT / "scripts/verify-release-local.sh").read_text(
            encoding="utf-8"
        )
        self.assertEqual(1, workflow.count("permissions:"))
        permissions = workflow.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
        self.assertEqual("  contents: read", permissions)
        self.assertNotIn("GH_TOKEN", release_runner)

    def test_declared_minimum_matches_the_tested_support_floor(self) -> None:
        minimum = exact_core_pin(ROOT / "requirements-ha-test.txt")
        current = exact_core_pin(ROOT / "requirements-ha-current.txt")
        self.assertEqual(_json_file(ROOT / "hacs.json")["homeassistant"], minimum)
        self.assertGreaterEqual(stable_version(current), stable_version(minimum))

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
        self.assertTrue(exception_keys)
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
        options = next(
            node.value
            for node in ast.walk(ast.parse(sensor_text))
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute) and target.attr == "_attr_options"
                for target in node.targets
            )
        )
        expected_states = set(ast.literal_eval(options))
        self.assertTrue(expected_states)

        self.assertEqual(
            expected_states,
            set(translations["entity"]["sensor"]["status"]["state"]),
        )
        self.assertIn("SensorDeviceClass.ENUM", sensor_text)

    def test_every_integration_json_file_is_valid(self) -> None:
        paths = [*INTEGRATION.rglob("*.json"), ROOT / "hacs.json"]
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsInstance(_json_file(path), dict)


if __name__ == "__main__":
    unittest.main()
