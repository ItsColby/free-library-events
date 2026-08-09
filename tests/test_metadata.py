"""Static contract tests for Home Assistant metadata."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components/free_library_events"


def _json_file(path: Path) -> dict[str, object]:
    """Load one integration-owned JSON metadata file."""

    return json.loads(path.read_text(encoding="utf-8"))


class HomeAssistantMetadataTests(unittest.TestCase):
    """Keep translated metadata aligned with the public HA surfaces."""

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

    def test_workflow_validates_every_integration_json_file(self) -> None:
        release_runner = (ROOT / "scripts/verify-release-local.sh").read_text(
            encoding="utf-8"
        )
        integration_json = {
            path.relative_to(ROOT).as_posix() for path in INTEGRATION.rglob("*.json")
        }

        for path in integration_json:
            with self.subTest(path=path):
                self.assertIn(f'"{path}"', release_runner)

    def test_ha_test_module_fails_closed_when_the_harness_is_unavailable(self) -> None:
        integration_tests = (ROOT / "tests/test_integration_ha.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("unittest.SkipTest", integration_tests)
        self.assertNotIn("except ModuleNotFoundError", integration_tests)


if __name__ == "__main__":
    unittest.main()
