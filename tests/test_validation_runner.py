"""Behavioral checks for validation orchestration without installing dependencies."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ValidationRunnerTests(unittest.TestCase):
    """Exercise real Bash control flow with isolated executable stand-ins."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "checkout with spaces"
        (self.repo / "scripts").mkdir(parents=True)
        self.runner = self.repo / "scripts/verify-release-local.sh"
        shutil.copyfile(ROOT / "scripts/verify-release-local.sh", self.runner)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.trace = self.root / "trace"
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(self.scratch),
            "TRACE": str(self.trace),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def executable(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def run_lane(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.runner), *args],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def install_python_stand_in(self) -> None:
        self.executable(
            "python",
            'printf "%s|%s|%s\\n" "$PWD" "${VIRTUAL_ENV:-}" "$*" >> "$TRACE"\n'
            'if [[ "$*" == "-m venv "* ]]; then\n'
            '  mkdir -p "$3/bin"\n'
            '  cp "$0" "$3/bin/python"\n'
            'elif [[ "$*" == *"shellcheck-py=="* ]]; then\n'
            '  printf "#!/usr/bin/env bash\\nexit 0\\n" > "$(dirname "$0")/shellcheck"\n'
            '  chmod +x "$(dirname "$0")/shellcheck"\n'
            'elif [[ "$*" == "-m pip check" ]]; then\n'
            '  exit "${PIP_CHECK_EXIT:-0}"\n'
            "fi\n",
        )
        self.executable("pytest", 'printf "pytest:%s\\n" "$*" >> "$TRACE"\n')

    def test_bad_arguments_and_help_do_not_create_snapshots_or_run_tools(self) -> None:
        for args, expected in (
            (("unknown",), 2),
            (("unit", "unknown"), 2),
            (("unit", "native", "unused", "extra"), 2),
            (("--help",), 0),
        ):
            with self.subTest(args=args):
                result = self.run_lane(*args)
                self.assertEqual(expected, result.returncode, result.stderr)
                self.assertIn("Usage:", result.stdout + result.stderr)
                self.assertEqual([], list(self.scratch.iterdir()))
                self.assertFalse(self.trace.exists())

    def test_native_lanes_use_separate_environments_and_repository_cwd(self) -> None:
        self.install_python_stand_in()
        for lane in ("minimum", "current"):
            result = self.run_lane(lane, "native")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f"Local validation passed: {lane} (native)", result.stdout)
            self.assertEqual([], list(self.scratch.iterdir()))
        records = self.trace.read_text(encoding="utf-8").splitlines()
        installs = [line.split("|", 2) for line in records if "|-m pip install" in line]
        environments = {parts[1] for parts in installs}
        self.assertEqual(2, len(environments))
        self.assertTrue(all(parts[0] == str(self.repo) for parts in installs))
        self.assertTrue(all(not Path(value).exists() for value in environments))

    def test_dependency_failure_stops_before_tests_and_cleans_environment(self) -> None:
        self.install_python_stand_in()
        self.env["PIP_CHECK_EXIT"] = "17"
        result = self.run_lane("minimum", "native")
        self.assertEqual(17, result.returncode, result.stderr)
        self.assertNotIn("pytest:", self.trace.read_text(encoding="utf-8"))
        self.assertNotIn("Local validation passed", result.stdout)
        self.assertEqual([], list(self.scratch.iterdir()))

    def test_actionlint_failure_cleans_tools_and_uses_repository_cwd(self) -> None:
        self.install_python_stand_in()
        self.executable(
            "go",
            'printf "%s\\n" "$PWD" > "$TRACE"\n'
            "cat > \"$GOBIN/actionlint\" <<'SCRIPT'\n"
            "#!/usr/bin/env bash\n"
            'command -v shellcheck >> "$TRACE"\n'
            "exit 19\nSCRIPT\n"
            'chmod +x "$GOBIN/actionlint"\n',
        )
        result = self.run_lane("unit", "native")
        self.assertEqual(19, result.returncode, result.stderr)
        lines = self.trace.read_text(encoding="utf-8").splitlines()
        self.assertEqual(str(self.repo), lines[0])
        self.assertTrue(Path(lines[1]).is_relative_to(self.scratch))
        self.assertEqual("shellcheck", Path(lines[1]).name)
        self.assertEqual([], list(self.scratch.iterdir()))

    def test_snapshot_includes_working_changes_and_cleans_after_failure(self) -> None:
        def git(*args: str) -> None:
            subprocess.run(
                ["git", "-C", str(self.repo), *args],
                env=self.env,
                check=True,
                capture_output=True,
                timeout=10,
            )

        git("init", "-q")
        (self.repo / ".gitignore").write_text("private.txt\n", encoding="utf-8")
        (self.repo / "tracked.txt").write_text("original", encoding="utf-8")
        git("add", "--all")
        (self.repo / "tracked.txt").write_text("changed", encoding="utf-8")
        (self.repo / "new file.txt").write_text("new", encoding="utf-8")
        (self.repo / "private.txt").write_text("private", encoding="utf-8")
        self.executable(
            "podman",
            "while (( $# )); do\n"
            '  if [[ "$1" == -v ]]; then\n'
            '    snapshot="${2%%:/github/*}"\n'
            '    [[ "$(cat "$snapshot/tracked.txt")" == changed ]]\n'
            '    [[ -f "$snapshot/new file.txt" && ! -e "$snapshot/private.txt" ]]\n'
            '    git -C "$snapshot" ls-files --error-unmatch "new file.txt" >/dev/null\n'
            '    printf "snapshot-ok\\n" > "$TRACE"\n'
            "    exit 23\n"
            "  fi\n"
            "  shift\n"
            "done\nexit 99\n",
        )
        result = self.run_lane("release", "container")
        self.assertEqual(23, result.returncode, result.stderr)
        self.assertEqual("snapshot-ok\n", self.trace.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.scratch.iterdir()))
        self.assertEqual("changed", (self.repo / "tracked.txt").read_text())
        self.assertTrue((self.repo / "private.txt").exists())


if __name__ == "__main__":
    unittest.main()
