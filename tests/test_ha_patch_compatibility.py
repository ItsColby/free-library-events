"""Tests for the bounded Home Assistant patch-forward checker."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_ha_patch_compatibility import (
    CompatibilityError,
    exact_core_pin,
    harness_core_pin,
    validate_harness_window,
    validate_patch_window,
    validate_pip_check,
)


class HomeAssistantPatchCompatibilityTests(unittest.TestCase):
    def test_exact_core_pin_requires_one_stable_pin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text("# target\nhomeassistant==2026.8.1\n", encoding="utf-8")
            self.assertEqual("2026.8.1", exact_core_pin(path))

            path.write_text(
                "homeassistant==2026.8.0\nhomeassistant==2026.8.1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CompatibilityError, "exactly one"):
                exact_core_pin(path)

    def test_patch_window_rejects_equal_cross_month_and_prerelease_versions(
        self,
    ) -> None:
        validate_patch_window("2026.8.0", "2026.8.1")
        for minimum, current in (
            ("2026.8.0", "2026.8.0"),
            ("2026.8.1", "2026.8.0"),
            ("2026.7.9", "2026.8.0"),
            ("2026.8.0", "2026.8.1b0"),
        ):
            with (
                self.subTest(minimum=minimum, current=current),
                self.assertRaises(CompatibilityError),
            ):
                validate_patch_window(minimum, current)

    def test_harness_metadata_requires_one_exact_core_pin(self) -> None:
        self.assertEqual(
            "2026.8.0",
            harness_core_pin(["homeassistant==2026.8.0", "pytest>=8"]),
        )
        for requirements in (
            [],
            ["homeassistant>=2026.8.0"],
            ["homeassistant==2026.8.0", "homeassistant==2026.8.1"],
        ):
            with (
                self.subTest(requirements=requirements),
                self.assertRaises(CompatibilityError),
            ):
                harness_core_pin(requirements)

    def test_harness_pin_stays_inside_supported_patch_window(self) -> None:
        validate_harness_window("2026.8.0", "2026.8.0", "2026.8.1")
        validate_harness_window("2026.8.0", "2026.8.1", "2026.8.1")
        for harness in ("2026.7.9", "2026.8.2", "2026.8.1b0"):
            with (
                self.subTest(harness=harness),
                self.assertRaises(CompatibilityError),
            ):
                validate_harness_window("2026.8.0", harness, "2026.8.1")

    def test_pip_check_accepts_clean_environment(self) -> None:
        self.assertEqual(
            "dependency-closed",
            validate_pip_check(
                0,
                "No broken requirements found.\n",
                harness_version="0.13.354",
                harness_core="2026.8.0",
                current_core="2026.8.1",
            ),
        )

    def test_pip_check_accepts_only_the_proven_harness_core_mismatch(self) -> None:
        mismatch = (
            "pytest-homeassistant-custom-component 0.13.354 has requirement "
            "homeassistant==2026.8.0, but you have homeassistant 2026.8.1.\n"
        )
        self.assertEqual(
            "single-known-harness-core-mismatch",
            validate_pip_check(
                1,
                mismatch,
                harness_version="0.13.354",
                harness_core="2026.8.0",
                current_core="2026.8.1",
            ),
        )
        for output in (
            mismatch
            + "other-package 1 requires missing-package, which is not installed.\n",
            mismatch.replace("0.13.354", "0.13.353"),
            mismatch.replace("2026.8.1", "2026.8.2"),
        ):
            with (
                self.subTest(output=output),
                self.assertRaisesRegex(CompatibilityError, "unexpected"),
            ):
                validate_pip_check(
                    1,
                    output,
                    harness_version="0.13.354",
                    harness_core="2026.8.0",
                    current_core="2026.8.1",
                )


if __name__ == "__main__":
    unittest.main()
