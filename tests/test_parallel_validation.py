"""Verify parallel container lanes preserve ordering, failure, and cleanup."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
GIT = shutil.which("git")
AFFECTED_PLANNER = r"""
import json
import os
import sys

if "--snapshot-plan" in sys.argv and os.environ.get("MATRIX_MUTATE_SOURCE"):
    from pathlib import Path
    source = Path(os.environ["MATRIX_MUTATE_SOURCE"])
    (source / "scripts/plan_validation.py").write_text("raise RuntimeError('changed original')")
if "--command" in sys.argv:
    raise RuntimeError("Lane command must come from the captured plan")
else:
    selected = os.environ["MATRIX_PLAN_LANES"].split()
    print(json.dumps({"jobs": {lane: lane in selected for lane in
          ("unit", "minimum", "current", "release", "hacs")}, "workflow": True,
          "safety": True, "paths": [], "base": "HEAD",
          "commands": {lane: "echo snapshot-command" for lane in selected}}))
"""

PODMAN_STAND_IN = r"""
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
events = Path(os.environ["MATRIX_EVENTS"])
failure = os.environ.get("MATRIX_FAIL")
lanes = set(os.environ["MATRIX_LANES"].split())
if any("actionlint@" in arg for arg in args):
    (events / "actionlint.done").touch()
    sys.exit(0)
if any("hassfest@" in arg for arg in args):
    for lane in lanes & {"minimum", "current"}:
        assert (events / (lane + ".done")).exists()
    (events / "release.done").touch()
    sys.exit(0)
if os.environ.get("MATRIX_MUTATE_SOURCE"):
    assert "snapshot-command" in args[-1], "Commands did not come from captured plan"
lane = ("current" if "requirements-ha-current.txt" in args[-1] else
        "minimum" if "requirements-ha-test.txt" in args[-1] else "unit")
mount = next(args[index + 1] for index, arg in enumerate(args[:-1])
             if arg == "-v" and ":/workspace:" in args[index + 1])
source, target, access = mount.split(":")
assert access == "ro"
assert args[:2] == ["run", "--rm"]
(events / (lane + ".mount")).write_text(source)
(events / (lane + ".started")).touch()
if lane == "unit":
    assert (events / "actionlint.done").exists()
else:
    if "unit" in lanes:
        assert (events / "unit.done").exists()
    peer = "minimum" if lane == "current" else "current"
    deadline = time.monotonic() + 5
    while peer in lanes and not (events / (peer + ".started")).exists():
        if time.monotonic() > deadline:
            raise SystemExit("The two HA lanes did not overlap")
        time.sleep(0.01)
    if os.environ.get("MATRIX_INTERRUPT"):
        while not (events / "interrupt.sent").exists():
            if time.monotonic() > deadline:
                raise SystemExit("The runner was not interrupted")
            time.sleep(0.01)
        time.sleep(0.1)
        assert Path(source).is_dir(), "Payload removed while interrupted lanes were active"
    if peer in lanes and failure == peer:
        while not (events / (peer + ".done")).exists():
            if time.monotonic() > deadline:
                raise SystemExit("The peer lane did not finish")
            time.sleep(0.01)
        time.sleep(0.05)
        assert Path(source).is_dir(), "Payload removed before both lanes finished"
(events / (lane + ".done")).touch()
sys.exit(23 if failure == lane else 0)
"""


@unittest.skipUnless(os.name == "posix" and BASH and GIT, "requires Linux Bash/Git")
class ParallelValidationTests(unittest.TestCase):
    """Use real shell jobs and snapshots with isolated external-tool stand-ins."""

    def setUp(self) -> None:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("GIT_")
        }
        environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        environment_patch = patch.dict(os.environ, environment, clear=True)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)

    def run_matrix(
        self,
        failure: str = "",
        *,
        interrupt: bool = False,
        mode: str = "all",
        lanes: tuple[str, ...] = ("unit", "minimum", "current", "release"),
        only: str = "",
        mutate_source: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], set[str], bool]:
        with tempfile.TemporaryDirectory(prefix="parallel validation ") as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "scripts").mkdir(parents=True)
            runner = source / "scripts" / "verify-release-local.sh"
            shutil.copyfile(ROOT / "scripts/verify-release-local.sh", runner)
            shutil.copyfile(
                ROOT / "scripts/check_public_safety.py",
                source / "scripts/check_public_safety.py",
            )
            (source / "scripts/plan_validation.py").write_text(
                AFFECTED_PLANNER, encoding="utf-8"
            )
            events = root / "events"
            events.mkdir()
            binary = root / "bin"
            binary.mkdir()
            podman = binary / "podman"
            podman.write_text(
                f"#!{sys.executable}\n{PODMAN_STAND_IN}", encoding="utf-8"
            )
            podman.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{binary}{os.pathsep}{os.environ['PATH']}",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "MATRIX_EVENTS": str(events),
                "MATRIX_PLAN_LANES": " ".join(lanes),
                "MATRIX_LANES": only or " ".join(lanes),
                "MATRIX_FAIL": failure,
                "VALIDATION_PYTHON": sys.executable,
                "MATRIX_INTERRUPT": "1" if interrupt else "",
                "MATRIX_MUTATE_SOURCE": str(source) if mutate_source else "",
            }
            for arguments in (
                ("init", "-q"),
                ("config", "user.name", "Validation Fixture"),
                ("config", "user.email", "fixture@example.test"),
                ("add", "-A"),
                ("commit", "-qm", "Validation fixture"),
            ):
                subprocess.run(
                    [str(GIT), "-C", str(source), *arguments],
                    env=env,
                    check=True,
                    capture_output=True,
                )
            with subprocess.Popen(
                [
                    str(BASH),
                    str(runner),
                    mode,
                    "container",
                    "",
                    *(["--only", only] if only else []),
                ],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as process:
                try:
                    if interrupt:
                        deadline = time.monotonic() + 10
                        while not all(
                            (events / f"{lane}.started").exists()
                            for lane in ("minimum", "current")
                        ):
                            if (
                                process.poll() is not None
                                or time.monotonic() > deadline
                            ):
                                self.fail("The two HA lanes did not start")
                            time.sleep(0.01)
                        process.send_signal(signal.SIGTERM)
                        (events / "interrupt.sent").touch()
                    stdout, stderr = process.communicate(timeout=30)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=10)
            result = subprocess.CompletedProcess(
                process.args, process.returncode, stdout, stderr
            )
            remaining_payload = any(
                Path(path.read_text()).exists() for path in events.glob("*.mount")
            )
            return result, {path.name for path in events.iterdir()}, remaining_payload

    def test_captured_commands_survive_original_planner_changes(self) -> None:
        result, events, remaining = self.run_matrix(
            mode="affected",
            mutate_source=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue({"unit.done", "minimum.done", "current.done"} <= events)
        self.assertFalse(remaining)

    def test_affected_selection_preserves_order_overlap_and_exclusions(self) -> None:
        for lanes, only in (
            (("unit", "minimum", "current", "release"), ""),
            (("minimum", "current"), ""),
            (("unit",), ""),
            (("minimum",), ""),
            (("current",), ""),
            (("release",), ""),
            (("minimum", "current"), "current"),
        ):
            with self.subTest(lanes=lanes, only=only):
                result, events, remaining = self.run_matrix(
                    mode="affected", lanes=lanes, only=only
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                expected = set((only,) if only else lanes)
                self.assertEqual(
                    {
                        name.removesuffix(".done")
                        for name in events
                        if name.endswith(".done") and name != "actionlint.done"
                    },
                    expected,
                )
                self.assertFalse(remaining)

    def test_affected_failure_drains_selected_lanes_and_blocks_release(self) -> None:
        for failure in ("unit", "minimum", "current"):
            with self.subTest(failure=failure):
                result, events, remaining = self.run_matrix(failure, mode="affected")
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("release.done", events)
                if failure == "unit":
                    self.assertNotIn("minimum.started", events)
                    self.assertNotIn("current.started", events)
                else:
                    self.assertTrue({"minimum.done", "current.done"} <= events)
                self.assertFalse(remaining)

    def test_affected_interrupt_drains_selected_lanes(self) -> None:
        result, events, remaining = self.run_matrix(mode="affected", interrupt=True)
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)
        self.assertTrue({"minimum.done", "current.done"} <= events)
        self.assertNotIn("release.done", events)
        self.assertFalse(remaining)

    def test_support_lanes_overlap_between_unit_and_release(self) -> None:
        result, events, remaining_payload = self.run_matrix()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue({"minimum.done", "current.done", "release.done"} <= events)
        self.assertFalse(remaining_payload)

    def test_either_failure_waits_for_both_lanes_and_blocks_release(self) -> None:
        for failure in ("minimum", "current"):
            with self.subTest(failure=failure):
                result, events, remaining_payload = self.run_matrix(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue({"minimum.done", "current.done"} <= events)
                self.assertNotIn("release.done", events)
                self.assertFalse(remaining_payload)

    def test_unit_failure_does_not_start_support_lanes(self) -> None:
        result, events, remaining_payload = self.run_matrix("unit")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("minimum.started", events)
        self.assertNotIn("current.started", events)
        self.assertNotIn("release.done", events)
        self.assertFalse(remaining_payload)

    def test_interrupt_waits_for_active_lanes_before_removing_payload(self) -> None:
        result, events, remaining_payload = self.run_matrix(interrupt=True)
        self.assertTrue(
            {"minimum.done", "current.done"} <= events, result.stdout + result.stderr
        )
        self.assertNotIn("release.done", events)
        self.assertNotIn("Local validation passed", result.stdout)
        self.assertFalse(remaining_payload)
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
