"""Manage the Qt overlay as a separate process from the Tk control panel."""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable


class OverlayProcess:
    """Launch the overlay with the current interpreter and forward its output."""

    def __init__(self, log: Callable[[str], None]) -> None:
        """Create a stopped overlay manager."""
        self.log = log
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        """Start one overlay process, inheriting the game PID and display environment."""
        if self.process is not None:
            raise RuntimeError("Overlay process already started")
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "deadlock.esp"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.process = process
        threading.Thread(target=self._forward_output, args=(process,), daemon=True).start()

    def _forward_output(self, process: subprocess.Popen[str]) -> None:
        """Copy output to the panel without blocking the overlay on a full pipe."""
        if process.stdout is not None:
            try:
                for line in process.stdout:
                    self.log(f"ESP: {line.rstrip()}")
            finally:
                process.stdout.close()

    def poll(self) -> int | None:
        """Return the child exit code, or None while running (or not started)."""
        return self.process.poll() if self.process is not None else None

    def stop(self) -> None:
        """Terminate and reap the child; force termination if it does not exit."""
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.log("ESP did not exit promptly after being killed; waiting in background.")
                threading.Thread(target=process.wait, daemon=True).start()
