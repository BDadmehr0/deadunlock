"""Headless tests of aim-zone GUI state and validation."""

import importlib
import sys
import tempfile
import types
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


class Variable:
    """Minimal Tk variable substitute."""

    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ZoneGuiTests(unittest.TestCase):
    """Exercise the controls without requiring an X display or Tk installation."""

    @classmethod
    def setUpClass(cls):
        tk = types.ModuleType("tkinter")
        tk.BooleanVar = tk.StringVar = Variable
        tk.END = "end"
        tk.ttk = types.SimpleNamespace(
            LabelFrame=Mock(side_effect=lambda *a, **k: Mock()),
            Label=Mock(side_effect=lambda *a, **k: Mock()),
            Checkbutton=Mock(side_effect=lambda *a, **k: Mock()),
            Spinbox=Mock(side_effect=lambda *a, **k: Mock()),
        )
        tk.messagebox = Mock()
        tk.scrolledtext = Mock()
        with patch.dict(sys.modules, {"tkinter": tk}):
            cls.gui = importlib.import_module("deadlock.aimbot_gui")
        cls.tk = tk

    def setUp(self):
        self.app = self.gui.AimbotApp.__new__(self.gui.AimbotApp)
        self.app.settings = self.gui.AimbotSettings()
        self.app._build_zones_frame(Mock())
        for name in ("target_var", "grey_enabled", "grey_key", "yamato_enabled", "yamato_key",
                     "vindicta_enabled", "vindicta_key", "paradox_enabled", "paradox_r_key",
                     "paradox_e_key"):
            setattr(self.app, name, Variable(""))
        self.app.target_var.set("fov")

    def test_gui_startup_does_not_check_for_updates_or_open_browser(self):
        self.tk.messagebox.reset_mock()
        with patch.object(self.gui, "load_saved_settings", return_value=self.gui.AimbotSettings()), \
             patch.object(self.gui.AimbotApp, "_build_widgets"), \
             patch.object(self.gui.AimbotApp, "_process_log_queue"), \
             patch("socket.create_connection") as network, \
             patch("webbrowser.open") as browser:
            app = self.gui.AimbotApp(Mock())
        try:
            network.assert_not_called()
            browser.assert_not_called()
            self.tk.messagebox.askyesno.assert_not_called()
        finally:
            self.gui.logging.getLogger("deadlock.aimbot").removeHandler(app.log_handler)
            self.gui.logging.getLogger("offset_finder").removeHandler(app.log_handler)

    def test_build_id_is_local_and_handles_missing_git(self):
        subprocess = self.gui.get_build_sha.__globals__["subprocess"]
        with patch.object(subprocess, "check_output", return_value=b"abcdef123456\n"), \
             patch("socket.create_connection") as network:
            self.assertEqual(self.gui.get_build_sha(), "abcdef1")
            network.assert_not_called()
        with patch.object(subprocess, "check_output", side_effect=OSError("missing git")):
            self.assertEqual(self.gui.get_build_sha(), "unknown")

    def test_frozen_build_id_uses_bundled_version_file(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "version.txt").write_text("1234567890\n", encoding="utf-8")
            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", directory, create=True):
                self.assertEqual(self.gui.get_build_sha(), "1234567")

    def test_random_disables_custom_and_restores_it(self):
        app = self.app
        app.zone_enabled_vars["body"].set(True)
        app.zone_weight_vars["body"].set("45")
        app.random_zones_var.set(True)
        app._update_zone_controls()
        for zone in ("head", "body", "legs"):
            app.zone_checks[zone].state.assert_called_with(["disabled"])
            app.zone_entries[zone].state.assert_called_with(["disabled"])
        app._apply_widget_values()
        self.assertTrue(app.settings.random_zones)
        self.assertTrue(app.settings.body_enabled)
        self.assertEqual(app.settings.body_weight, 45)
        app.random_zones_var.set(False)
        app._update_zone_controls()
        app.zone_checks["body"].state.assert_called_with(["!disabled"])
        app.zone_entries["body"].state.assert_called_with(["!disabled"])
        app.zone_entries["legs"].state.assert_called_with(["disabled"])
        self.assertEqual(app.zone_weight_vars["body"].get(), "45")

    def test_head_adjustment_is_validated_and_applied_in_both_modes(self):
        app = self.app
        for random_mode in (False, True):
            app.random_zones_var.set(random_mode)
            app.head_vertical_var.set("-20")
            app._apply_widget_values()
            self.assertEqual(app.settings.head_vertical_offset, -20)
            for invalid in ("-101", "101", "1.5", ""):
                app.head_vertical_var.set(invalid)
                with self.assertRaisesRegex(ValueError, "Head height adjustment"):
                    app._apply_widget_values()
                self.assertEqual(app.settings.head_vertical_offset, -20)

    def test_invalid_manual_settings_are_rejected(self):
        app = self.app
        app.zone_weight_vars["head"].set("not a number")
        with self.assertRaises(ValueError):
            app._apply_widget_values()
        app.zone_weight_vars["head"].set("0")
        with self.assertRaises(ValueError):
            app._apply_widget_values()
        app.zone_weight_vars["head"].set("70")
        app.zone_enabled_vars["body"].set(True)
        app.zone_weight_vars["body"].set("20")
        app._apply_widget_values()
        self.assertEqual(app.settings.zone_weights(), {"head": 70, "body": 20})


class CombinedGuiTests(ZoneGuiTests):
    """Verify the panel manages overlay and bot lifecycles together."""

    def setUp(self):
        super().setUp()
        self.app.combined = True
        self.app.overlay = None
        self.app.esp_enabled = Variable(True)
        self.app.esp_status_label = Mock()
        self.app.esp_check = Mock()
        self.app.toggle_button = Mock()
        self.app.root = Mock()
        self.app.log_queue = Mock()
        self.app.is_running = False
        self.app.bot_thread = None
        self.app.bot = None
        self.app.stop_event = Mock()
        self.app.status_label = Mock()
        self.app.log_text = Mock()

    def test_start_and_stop_manage_the_overlay(self):
        overlay = Mock()
        with patch.object(self.gui, "OverlayProcess", return_value=overlay), \
             patch.object(self.gui, "save_settings"), \
             patch("socket.create_connection") as network, \
             patch("webbrowser.open") as browser, \
             patch.object(self.gui.threading, "Thread") as thread:
            self.app.start()
            network.assert_not_called()
            browser.assert_not_called()
            overlay.start.assert_called_once()
            self.assertIs(self.app.overlay, overlay)
            thread.return_value.start.assert_called_once()
            self.assertTrue(self.app.is_running)
            self.app.stop()
        overlay.stop.assert_called_once()
        self.assertIsNone(self.app.overlay)
        self.assertFalse(self.app.is_running)

    def test_start_failure_cleans_up_partially_started_overlay(self):
        overlay = Mock()
        overlay.start.side_effect = OSError("cannot launch")
        with patch.object(self.gui, "OverlayProcess", return_value=overlay), \
             patch.object(self.gui, "save_settings"), \
             patch.object(self.gui.messagebox, "showerror"):
            self.app.start()
        overlay.stop.assert_called_once()
        self.assertIsNone(self.app.overlay)
        self.assertFalse(self.app.is_running)

    def test_closing_panel_stops_managed_overlay(self):
        overlay = Mock()
        self.app.overlay = overlay
        self.app.is_running = True
        with patch.object(self.gui, "save_settings"):
            self.app.on_close()
        overlay.stop.assert_called_once()
        self.app.stop_event.set.assert_called_once()
        self.app.root.destroy.assert_called_once()

    def test_unchecked_esp_does_not_spawn_overlay(self):
        self.app.esp_enabled.set(False)
        with patch.object(self.gui, "OverlayProcess") as factory, \
             patch.object(self.gui, "save_settings"), \
             patch.object(self.gui.threading, "Thread"):
            self.app.start()
        factory.assert_not_called()
        self.assertTrue(self.app.is_running)

    def test_unexpected_exit_is_reported_and_reaped(self):
        overlay = Mock()
        overlay.poll.return_value = 3
        self.app.overlay = overlay
        self.app._poll_overlay(overlay)
        overlay.stop.assert_called_once()
        self.assertIsNone(self.app.overlay)
        self.assertIn("code 3", self.app.log_queue.put.call_args.args[0])
        self.app.esp_status_label.config.assert_called_with(text="ESP: exited", foreground="red")

    def test_bot_failure_stops_overlay(self):
        overlay = Mock()
        self.app.overlay = overlay
        self.app.is_running = True
        self.app.stop_event.is_set.return_value = False
        with patch.object(self.gui.messagebox, "showerror"):
            self.app._handle_bot_error("bad process")
        overlay.stop.assert_called_once()
        self.assertFalse(self.app.is_running)


if __name__ == "__main__":
    unittest.main()
