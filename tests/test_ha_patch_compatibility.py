"""Tests for the exact current Home Assistant lane and bounded patch exceptions."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.check_ha_patch_compatibility import (
    CompatibilityError,
    exact_core_pin,
    harness_core_pin,
    run,
    stable_version,
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
            ["homeassistant==2026.8.0; python_version < '3.10'"],
            ["homeassistant==2026.8.0", "homeassistant>=2026.8.0"],
            ["homeassistant==2026.8.0", "homeassistant==2026.8.1"],
        ):
            with (
                self.subTest(requirements=requirements),
                self.assertRaises(CompatibilityError),
            ):
                harness_core_pin(requirements)

    def test_harness_pin_stays_inside_supported_patch_window(self) -> None:
        validate_harness_window("2026.8.0", "2026.8.0", "2026.8.2")
        validate_harness_window("2026.8.0", "2026.8.1", "2026.8.2")
        for harness in ("2026.7.9", "2026.8.3", "2026.8.1b0"):
            with (
                self.subTest(harness=harness),
                self.assertRaises(CompatibilityError),
            ):
                validate_harness_window("2026.8.0", harness, "2026.8.2")

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

    def test_exact_core_pin_rejects_conditional_and_conflicting_requirements(
        self,
    ) -> None:
        for requirement in (
            "homeassistant==2026.8.0; python_version < '3.10'",
            "homeassistant==2026.8.0\nhomeassistant>=2026.8.1",
            "homeassistant==2026.8.0\nhomeassistant @ https://example.com/core.whl",
        ):
            with (
                self.subTest(requirement=requirement),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "requirements.txt"
                path.write_text(requirement, encoding="utf-8")
                with self.assertRaises(CompatibilityError):
                    exact_core_pin(path)

    def test_stable_versions_use_canonical_ascii_calver(self) -> None:
        for value in (
            "2026.0.0",
            "2026.13.0",
            "2026.08.0",
            "2026.8.01",
            "\uff12\uff10\uff12\uff16.8.0",
        ):
            with self.subTest(value=value), self.assertRaises(CompatibilityError):
                stable_version(value)

    def test_pip_check_rejects_inconsistent_closure_and_error_exit_codes(self) -> None:
        mismatch = (
            "pytest-homeassistant-custom-component 0.13.354 has requirement "
            "homeassistant==2026.8.0, but you have homeassistant 2026.8.1.\n"
        )
        for returncode, output in ((0, "No broken requirements found."), (2, mismatch)):
            with (
                self.subTest(returncode=returncode),
                self.assertRaises(CompatibilityError),
            ):
                validate_pip_check(
                    returncode,
                    output,
                    harness_version="0.13.354",
                    harness_core="2026.8.0",
                    current_core="2026.8.1",
                )

    def test_run_requires_exact_metadata_and_bounds_only_the_mismatch_exception(
        self,
    ) -> None:
        cases = (
            ("2026.9.1", "2026.9.1", "2026.9.1", 0, True),
            ("2026.8.2", "2026.8.0", "2026.8.2", 1, True),
            ("2026.9.1", "2026.8.0", "2026.9.1", 1, False),
            ("2026.9.1", "2026.9.1", "2026.9.0", 0, False),
            ("2026.8.0", "2026.8.0", "2026.8.0", 0, True),
            ("2026.7.9", "2026.7.9", "2026.7.9", 0, False),
            ("2026.8.0", "2026.7.9", "2026.8.0", 1, False),
        )
        for current, harness_core, installed, returncode, accepted in cases:
            with (
                self.subTest(
                    current=current, harness=harness_core, installed=installed
                ),
                tempfile.TemporaryDirectory() as directory,
            ):
                minimum_path = Path(directory) / "minimum.txt"
                current_path = Path(directory) / "current.txt"
                minimum_path.write_text("homeassistant==2026.8.0", encoding="utf-8")
                current_path.write_text(f"homeassistant=={current}", encoding="utf-8")
                harness = SimpleNamespace(
                    version="0.13.354", requires=[f"homeassistant=={harness_core}"]
                )
                output = (
                    "No broken requirements found."
                    if returncode == 0
                    else "pytest-homeassistant-custom-component 0.13.354 has requirement "
                    f"homeassistant=={harness_core}, but you have homeassistant {current}."
                )
                with (
                    patch(
                        "scripts.check_ha_patch_compatibility.metadata.version",
                        return_value=installed,
                    ),
                    patch(
                        "scripts.check_ha_patch_compatibility.metadata.distribution",
                        return_value=harness,
                    ),
                    patch(
                        "scripts.check_ha_patch_compatibility.subprocess.run",
                        return_value=subprocess.CompletedProcess(
                            [], returncode, output, ""
                        ),
                    ) as pip_check,
                ):
                    if accepted:
                        result = run(minimum_path, current_path)
                        self.assertEqual(
                            "dependency-closed"
                            if returncode == 0
                            else "single-known-harness-core-mismatch",
                            result,
                        )
                        self.assertEqual(60, pip_check.call_args.kwargs["timeout"])
                    else:
                        with self.assertRaises(CompatibilityError):
                            run(minimum_path, current_path)
                        pip_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
