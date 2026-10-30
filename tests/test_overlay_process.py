"""Tests for combined launcher and managed overlay lifecycle."""

import runpy
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from deadlock.overlay_process import OverlayProcess


class OverlayProcessTests(unittest.TestCase):
    """Start and stop the overlay child without Qt or a display."""

    def test_launch_forward_and_stop_a_real_child(self):
        output, ready = [], threading.Event()

        def log(line):
            output.append(line)
            ready.set()

        real_popen = subprocess.Popen

        def spawn(command, **kwargs):
            self.assertEqual(command, [sys.executable, "-u", "-m", "deadlock.esp"])
            return real_popen([sys.executable, "-u", "-c",
                               "import time; print('ready'); time.sleep(60)"], **kwargs)

        overlay = OverlayProcess(log)
        with patch("deadlock.overlay_process.subprocess.Popen", side_effect=spawn):
            overlay.start()
        try:
            self.assertTrue(ready.wait(5), "child output was not forwarded")
            self.assertIn("ESP: ready", output)
            self.assertIsNone(overlay.poll())
            with self.assertRaises(RuntimeError):
                overlay.start()
            process = overlay.process
        finally:
            overlay.stop()
        self.assertIsNone(overlay.process)
        self.assertIsNotNone(process.poll())
        overlay.stop()

    def test_force_kills_and_reaps_unresponsive_child(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("esp", 1), 0]
        overlay = OverlayProcess(Mock())
        overlay.process = process
        overlay.stop()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertIsNone(overlay.process)

    def test_reaps_already_exited_child_without_signalling(self):
        process = Mock()
        process.poll.return_value = 2
        overlay = OverlayProcess(Mock())
        overlay.process = process
        self.assertEqual(overlay.poll(), 2)
        overlay.stop()
        process.terminate.assert_not_called()
        process.wait.assert_called_once()

    def test_package_entrypoint_requests_combined_mode(self):
        fake_gui = Mock()
        with patch.dict(sys.modules, {"deadlock.aimbot_gui": fake_gui}):
            runpy.run_module("deadlock", run_name="__main__")
        fake_gui.main.assert_called_once_with(combined=True)


if __name__ == "__main__":
    unittest.main()
