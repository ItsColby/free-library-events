"""Static contracts for product metadata."""

from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components/free_library_events"


def _json_file(path: Path) -> dict[str, object]:
    """Load one product-owned JSON metadata file."""

    return json.loads(path.read_text(encoding="utf-8"))


def _core_version(path: Path) -> tuple[int, ...]:
    """Return the single exact Home Assistant pin in a requirements file."""

    pins = re.findall(
        r"^homeassistant==(\d+)\.(\d+)\.(\d+)$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if len(pins) != 1:
        raise AssertionError(f"{path.name} must pin exactly one Home Assistant")
    return tuple(int(part) for part in pins[0])


class HomeAssistantMetadataTests(unittest.TestCase):
    """Keep public metadata aligned with the tested support floor."""

    def test_declared_minimum_matches_the_tested_support_floor(self) -> None:
        minimum = _core_version(ROOT / "requirements-ha-test.txt")
        current = _core_version(ROOT / "requirements-ha-current.txt")
        declared = str(_json_file(ROOT / "hacs.json")["homeassistant"])
        self.assertEqual(tuple(int(part) for part in declared.split(".")), minimum)
        self.assertGreaterEqual(current, minimum)

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


if __name__ == "__main__":
    unittest.main()
