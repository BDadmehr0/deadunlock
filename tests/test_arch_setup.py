"""Tests for the Arch installer without invoking pacman or pip."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ArchSetupTests(unittest.TestCase):
    """Run the installer against isolated, stubbed system commands."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        self.script = self.root / "scripts" / "setup-arch.sh"
        shutil.copy(Path(__file__).resolve().parents[1] / "scripts/setup-arch.sh", self.script)
        (self.root / "requirements.txt").write_text("test-package\n", encoding="utf-8")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.log"
        self.env = os.environ.copy()
        self.env.update(PATH=f"{self.bin}:/usr/bin:/bin", LOG_FILE=str(self.log))
        self._stub("pacman", "exit 0")
        self._stub("sudo", 'echo "sudo $*" >> "$LOG_FILE"')
        self._stub(
            "python3",
            '''if [[ "$1" == "-c" ]]; then
    exit 0
fi
echo "python3 $*" >> "$LOG_FILE"
mkdir -p "$3/bin"
cat > "$3/bin/python" <<'PYTHON'
#!/bin/bash
echo "venv-python $*" >> "$LOG_FILE"
exit "${PIP_EXIT:-0}"
PYTHON
chmod +x "$3/bin/python"''',
        )

    def _stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/bin/bash\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def _run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.script), *args],
            cwd="/",
            env={**self.env, **env},
            text=True,
            capture_output=True,
            check=False,
        )

    def test_default_and_reuse(self) -> None:
        first = self._run()
        self.assertEqual(first.returncode, 0, first.stderr)
        calls = self.log.read_text(encoding="utf-8")
        self.assertIn("sudo pacman -Syu --needed python tk", calls)
        self.assertIn(f"python3 -m venv {self.root}/.venv", calls)
        self.assertIn(f"venv-python -m pip install -r {self.root}/requirements.txt", calls)
        second = self._run("--skip-system")
        self.assertEqual(second.returncode, 0, second.stderr)
        calls = self.log.read_text(encoding="utf-8")
        self.assertEqual(calls.count("sudo pacman"), 1)
        self.assertEqual(calls.count("python3 -m venv"), 1)
        self.assertEqual(calls.count("venv-python -m pip install"), 2)

    def test_install_failure_is_reported(self) -> None:
        result = self._run("--skip-system", PIP_EXIT="7")
        self.assertEqual(result.returncode, 7)
        self.assertNotIn("Setup complete", result.stdout)

    def test_help_and_invalid_option(self) -> None:
        self.assertEqual(self._run("--help").returncode, 0)
        self.assertEqual(self._run("--wrong").returncode, 2)
        self.assertFalse(self.log.exists())

    def test_incomplete_environment_is_not_overwritten(self) -> None:
        (self.root / ".venv").mkdir()
        result = self._run("--skip-system")
        self.assertEqual(result.returncode, 1)
        self.assertIn("incomplete", result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
