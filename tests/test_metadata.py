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


class HomeAssistantMetadataTests(unittest.TestCase):
    """Keep public metadata aligned with the tested support floor."""

    def test_declared_minimum_matches_the_tested_support_floor(self) -> None:
        minimum = str(_json_file(ROOT / "hacs.json")["homeassistant"])
        self.assertEqual(minimum, _exact_core_pin("ha-current"))
        self.assertIn(minimum, (ROOT / "README.md").read_text(encoding="utf-8"))

    def integration_source(self) -> str:
        return "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(INTEGRATION.glob("*.py"))
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
        init_text = self.integration_source()
        strings = _json_file(INTEGRATION / "translations/en.json")
        exception_keys = self.translation_keys(
            init_text, {"HomeAssistantError", "ServiceValidationError"}
        )
        self.assertTrue(exception_keys)
        self.assertTrue(exception_keys <= set(strings["exceptions"]))

    def test_coordinator_failures_are_translated(self) -> None:
        coordinator_text = self.integration_source()
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
            self.assertNotRegex(service_block, r"(?m)^\s+(name|description):")
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
        self.assertEqual(
            {platform: set(keys) for platform, keys in translations["entity"].items()},
            {platform: set(keys) for platform, keys in icons["entity"].items()},
        )

    def test_config_error_keys_are_translated(self) -> None:
        tree = ast.parse((INTEGRATION / "config.py").read_text(encoding="utf-8"))
        keys: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id in {"ValueError", "TypeError"}
                and node.exc.args
                and isinstance(node.exc.args[0], ast.Constant)
            ):
                keys.add(node.exc.args[0].value)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_normalize_integer"
                and isinstance(node.args[1], ast.Constant)
            ):
                keys.add(node.args[1].value)
        translations = _json_file(INTEGRATION / "translations/en.json")
        translated = set(translations["config"]["error"]) | set(
            translations["options"]["error"]
        )
        self.assertTrue(keys)
        self.assertEqual(set(), keys - translated)

    def test_copied_limits_match_their_constants(self) -> None:
        source = (INTEGRATION / "const.py").read_text(encoding="utf-8")
        namespace: dict[str, object] = {}
        exec(  # noqa: S102 - evaluates this repository's own constants
            "\n".join(
                line
                for line in source.splitlines()
                if re.match(r"(MIN|MAX)_(CALENDAR|SCAN|WEBCAL)\w* = ", line)
            ),
            namespace,
        )
        minutes = f"{namespace['MIN_CALENDAR_DURATION']} to {namespace['MAX_CALENDAR_DURATION']} minutes"
        seconds = f"{namespace['MIN_SCAN_INTERVAL']} to {namespace['MAX_SCAN_INTERVAL']} seconds"
        translations = _json_file(INTEGRATION / "translations/en.json")
        for section in ("config", "options"):
            errors = translations[section]["error"]
            self.assertIn(minutes, errors["invalid_calendar_duration"])
            self.assertIn(seconds, errors["invalid_scan_interval"])
        dash = chr(0x2013)
        usage = (ROOT / "docs/usage.md").read_text(encoding="utf-8")
        self.assertIn(
            f"{namespace['MIN_CALENDAR_DURATION']}{dash}{namespace['MAX_CALENDAR_DURATION']}",
            usage,
        )
        self.assertIn(
            f"{namespace['MIN_SCAN_INTERVAL']}{dash}{namespace['MAX_SCAN_INTERVAL']}",
            usage,
        )
        self.assertIn(f"1{dash}{namespace['MAX_WEBCAL_NAME_LENGTH']} c", usage)

    def test_translations_hold_no_unresolved_key_references(self) -> None:
        text = (INTEGRATION / "translations/en.json").read_text(encoding="utf-8")
        self.assertNotIn("[%key:", text)


if __name__ == "__main__":
    unittest.main()
