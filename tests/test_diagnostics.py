"""Tests for the X11 overlay setup and read-only game diagnostics."""

import ctypes
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deadlock.aimbot import Aimbot
from deadlock.diagnostics import main, report_players
from deadlock.display_config import configure_overlay_display
from deadlock.heroes import HeroIds
from deadlock.linux_process import LinuxProcess
from deadlock.memory import EntityUnavailable


class DisplayConfigurationTests(unittest.TestCase):
    """Check Qt platform selection before creating QApplication."""

    def test_default_xcb_on_x11(self):
        environment = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}
        self.assertFalse(configure_overlay_display(environment))
        self.assertEqual(environment["QT_QPA_PLATFORM"], "xcb")

    def test_xwayland_warns_and_explicit_xcb_is_preserved(self):
        environment = {
            "DISPLAY": ":1", "XDG_SESSION_TYPE": "wayland", "QT_QPA_PLATFORM": "xcb"
        }
        self.assertTrue(configure_overlay_display(environment))
        self.assertEqual(environment["QT_QPA_PLATFORM"], "xcb")

    def test_invalid_or_missing_display_has_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "X11 DISPLAY"):
            configure_overlay_display({})
        with self.assertRaisesRegex(RuntimeError, "QT_QPA_PLATFORM=xcb"):
            configure_overlay_display({"DISPLAY": ":0", "QT_QPA_PLATFORM": "wayland"})


class ReadOnlyDiagnosticsTests(unittest.TestCase):
    """Check that player reports cannot write to process memory."""

    def test_os_handle_rejects_writes(self):
        value = ctypes.c_float(4.5)
        process = LinuxProcess(os.getpid(), read_only=True)
        try:
            self.assertAlmostEqual(process.read_float(ctypes.addressof(value)), 4.5)
            with self.assertRaises(OSError):
                process.write_float(ctypes.addressof(value), 2.0)
            self.assertAlmostEqual(value.value, 4.5)
        finally:
            process.close()

    def test_report_explains_target_filters_and_read_errors(self):
        def read_entity(index):
            if index == 0:
                return {"hero": HeroIds.Wraith, "team": 1, "health": 500}
            if index == 1:
                return {"hero": HeroIds.Abrams, "team": 1, "health": 200}
            if index == 2:
                return {"hero": HeroIds.Haze, "team": 2, "health": 0}
            if index == 3:
                return {"hero": HeroIds.Ivy, "team": 2, "health": 100}
            raise EntityUnavailable("missing player data")

        mem = SimpleNamespace(read_entity=Mock(side_effect=read_entity), set_angles=Mock())
        output = io.StringIO()
        report_players(mem, output)
        text = output.getvalue()
        self.assertIn("Local: hero=Wraith team=1 health=500", text)
        self.assertIn("Slot 1: hero=Abrams team=1 health=200 -> same team", text)
        self.assertIn("Slot 2: hero=Haze team=2 health=0 -> non-positive health", text)
        self.assertIn("Slot 3: hero=Ivy team=2 health=100 -> candidate", text)
        self.assertIn("unreadable=12", text)
        self.assertIn("does not verify camera", text)
        mem.set_angles.assert_not_called()

    def test_unavailable_local_does_not_classify_enemy(self):
        def read_entity(index):
            if index == 0:
                raise EntityUnavailable("Unknown hero ID 0")
            return {"hero": HeroIds.Wraith, "team": 2, "health": 100}

        output = io.StringIO()
        report_players(SimpleNamespace(read_entity=read_entity), output)
        self.assertIn("Local player unavailable: Unknown hero ID 0", output.getvalue())
        self.assertIn("local unavailable=15", output.getvalue())
        self.assertNotIn("-> candidate", output.getvalue())

    def test_extended_scan_marks_candidates_outside_aim_range(self):
        def read_entity(index):
            if index == 0:
                return {"hero": HeroIds.Paradox, "team": 2, "health": 1821}
            if index == 52:
                return {"hero": HeroIds.Wraith, "team": 3, "health": 500}
            raise EntityUnavailable("not a player")

        output = io.StringIO()
        mem = SimpleNamespace(read_entity=Mock(side_effect=read_entity), set_angles=Mock())
        report_players(mem, output, slots=64, show_unreadable=False)
        text = output.getvalue()
        self.assertIn("Slot 52: hero=Wraith team=3 health=500 -> candidate outside default scan", text)
        self.assertIn("Additional unreadable slots omitted: 60", text)
        self.assertIn("unreadable=63", text)
        self.assertEqual(mem.read_entity.call_count, 65)
        mem.set_angles.assert_not_called()

    def test_extended_scan_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 2048"):
            report_players(SimpleNamespace(), io.StringIO(), slots=2049)
        with patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as exc:
                main(["--slots", "0"])
        self.assertEqual(exc.exception.code, 2)

    def test_main_uses_read_only_pid_and_closes_handle(self):
        process = SimpleNamespace(close=Mock())
        memory = SimpleNamespace(pm=process, read_entity=Mock(side_effect=OSError("no data")))
        with patch("deadlock.diagnostics.DeadlockMemory", return_value=memory) as opener:
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main(["--pid", "123"]), 0)
        opener.assert_called_once_with(read_only=True, pid=123)
        process.close.assert_called_once()


class NoTargetLoggingTests(unittest.TestCase):
    """Target-scan failures should be observable without flooding the log."""

    def test_no_target_summary_is_throttled(self):
        def read_entity(index):
            if index == 0:
                return {"hero": HeroIds.Wraith, "team": 1, "health": 500, "aim_angle": 0}
            if index == 1:
                return {"hero": HeroIds.Ivy, "team": 1, "health": 100}
            if index == 2:
                return {"hero": HeroIds.Haze, "team": 2, "health": 0}
            raise EntityUnavailable("missing player data")

        memory = SimpleNamespace(
            read_entity=Mock(side_effect=read_entity),
            camera_position=Mock(return_value=(0, 0, 0)),
            current_angles=Mock(return_value=(0, 0)),
            set_angles=Mock(),
        )
        device = Mock()
        device.button_down.side_effect = lambda button: button == 1
        with patch("deadlock.aimbot.X11Input", return_value=device):
            bot = Aimbot(memory)
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 3:
                bot.stop()

        with patch("deadlock.aimbot.time.sleep", side_effect=sleep), \
             patch("deadlock.aimbot.time.monotonic", return_value=100):
            with self.assertLogs("deadlock.aimbot", level="WARNING") as logs:
                bot.run()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("13 unreadable slots, 1 same-team, 1 non-positive health", logs.output[0])
        self.assertIn("slot 3: missing player data", logs.output[0])
        memory.set_angles.assert_not_called()
        device.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
