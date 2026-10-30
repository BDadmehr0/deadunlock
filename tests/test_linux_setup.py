"""Tests for the multi-distribution installer using stubbed commands."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class LinuxSetupTests(unittest.TestCase):
    """Exercise detection and failures without modifying the host system."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        self.script = self.root / "scripts/setup-linux.sh"
        shutil.copy(Path(__file__).resolve().parents[1] / "scripts/setup-linux.sh", self.script)
        (self.root / "requirements.txt").write_text("example\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.release = self.root / "os-release"
        self.log = self.root / "calls.log"
        self.env = {**os.environ, "PATH": f"{self.bin}:/usr/bin:/bin", "LOG_FILE": str(self.log),
                    "DEADUNLOCK_OS_RELEASE": str(self.release)}
        for manager in ("apt-get", "pacman", "dnf", "zypper"):
            self._stub(manager, "exit 0")
        self._stub("sudo", 'echo "sudo $*" >> "$LOG_FILE"; exit "${SYSTEM_EXIT:-0}"')
        self._stub("python3", '''if [[ "$1" == "-c" ]]; then
    exit "${SYSTEM_PYTHON_EXIT:-0}"
fi
echo "python3 $*" >> "$LOG_FILE"
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'PYTHON'
#!/bin/bash
if [[ "$1" == "-c" ]]; then
    if [[ "$2" == *tkinter* ]]; then exit "${TK_EXIT:-0}"; fi
    exit "${VENV_VERSION_EXIT:-0}"
fi
echo "venv-python $*" >> "$LOG_FILE"
exit "${PIP_EXIT:-0}"
PYTHON
chmod +x "$3/bin/python"''')

    def _stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def _run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(self.script), *args], cwd="/",
                              env={**self.env, **env}, text=True, capture_output=True)

    def test_supported_families_and_release_like(self) -> None:
        cases = [
            ('ID=arch\n', 'sudo pacman -Syu --needed', 'xcb-util-cursor'),
            ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', 'sudo apt-get install', 'python3-tk'),
            ('ID=fedora\n', 'sudo dnf install', 'python3-tkinter'),
            ('ID=opensuse-tumbleweed\nID_LIKE="opensuse suse"\n', 'sudo zypper install',
             'libxcb-cursor0'),
        ]
        for release, expected, package in cases:
            with self.subTest(release=release):
                self.release.write_text(release, encoding="utf-8")
                self.log.unlink(missing_ok=True)
                result = self._run()
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.log.read_text(encoding="utf-8")
                self.assertIn(expected, calls)
                self.assertIn(package, calls)
                self.assertIn(f"venv-python -m pip install -r {self.root}/requirements.txt", calls)
                self.assertIn(".venv/bin/python -m deadlock", result.stdout)
                if "apt-get" in expected:
                    self.assertIn("sudo apt-get update", calls)

    def test_skip_system_reuse_and_pip_failure(self) -> None:
        first = self._run("--skip-system")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self._run("--skip-system", PIP_EXIT="7")
        self.assertEqual(second.returncode, 7)
        self.assertNotIn("Setup complete", second.stdout)
        calls = self.log.read_text(encoding="utf-8")
        self.assertNotIn("sudo", calls)
        self.assertEqual(calls.count("python3 -m venv"), 1)

    def test_unknown_and_malicious_os_release_do_not_run_commands(self) -> None:
        marker = self.root / "should-not-exist"
        self.release.write_text(f'ID="$(touch {marker})"\n', encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Unsupported distribution", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(self.log.exists())
        self.assertEqual(self._run("--skip-system").returncode, 0)

    def test_incomplete_venv_and_missing_tk_fail_clearly(self) -> None:
        (self.root / ".venv").mkdir()
        result = self._run("--skip-system")
        self.assertEqual(result.returncode, 1)
        self.assertIn("incomplete", result.stderr)
        (self.root / ".venv").rmdir()
        result = self._run("--skip-system", TK_EXIT="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Tkinter is unavailable", result.stderr)
        self.assertNotIn("venv-python -m pip", self.log.read_text(encoding="utf-8"))
        result = self._run("--skip-system", VENV_VERSION_EXIT="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Existing .venv needs Python 3.11", result.stderr)
        self.assertNotIn("venv-python -m pip", self.log.read_text(encoding="utf-8"))

    def test_system_failure_and_invalid_options(self) -> None:
        self.release.write_text("ID=fedora\n", encoding="utf-8")
        self.assertEqual(self._run("--help").returncode, 0)
        self.assertEqual(self._run("--wrong").returncode, 2)
        self.assertEqual(self._run("--skip-system", "extra").returncode, 2)
        result = self._run(SYSTEM_EXIT="8")
        self.assertEqual(result.returncode, 8)
        self.assertNotIn("Setup complete", result.stdout)
        self.assertNotIn("venv-python -m pip", self.log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
