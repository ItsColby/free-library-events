"""Static contracts for product metadata."""

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


def _exact_core_pin(group: str) -> str:
    """Read one exact stable Home Assistant pin from a pyproject dependency group."""

    with (ROOT / "pyproject.toml").open("rb") as file:
        requirements = tomllib.load(file)["dependency-groups"][group]
    pins = []
    for requirement in requirements:
        if not re.match(
            r"homeassistant(?=[^A-Za-z0-9_.-]|$)", requirement, re.IGNORECASE
        ):
            continue
        match = re.fullmatch(
            r"homeassistant\s*==\s*([0-9]{4}\.(?:[1-9]|1[0-2])\.(?:0|[1-9][0-9]*))",
            requirement,
            re.IGNORECASE,
        )
        if match is None:
            raise AssertionError(
                f"{group} must use an unconditional stable exact Home Assistant pin"
            )
        pins.append(match.group(1))
    if len(pins) != 1:
        raise AssertionError(f"{group} must contain exactly one Home Assistant pin")
    return pins[0]


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


class HomeAssistantMetadataTests(unittest.TestCase):
    """Keep public metadata aligned with the tested support floor."""

    def test_declared_minimum_matches_the_tested_support_floor(self) -> None:
        minimum = _exact_core_pin("ha-minimum")
        current = _exact_core_pin("ha-current")
        self.assertEqual(str(_json_file(ROOT / "hacs.json")["homeassistant"]), minimum)
        self.assertGreaterEqual(_version(current), _version(minimum))

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
