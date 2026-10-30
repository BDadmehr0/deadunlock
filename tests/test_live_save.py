"""Headless tests of live settings persistence and restart behavior."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_zone_gui as gui_helpers


class Scheduler:
    """Minimal Tk-like scheduler for deterministic debounce tests."""

    def __init__(self):
        self.pending = {}
        self.next_id = 0

    def after(self, _delay, callback):
        self.next_id += 1
        job = str(self.next_id)
        self.pending[job] = callback
        return job

    def after_cancel(self, job):
        self.pending.pop(job, None)

    def flush(self):
        jobs, self.pending = list(self.pending.values()), {}
        for callback in jobs:
            callback()


class LiveSaveTests(unittest.TestCase):
    """Exercise disk persistence without opening Tk or the game."""

    @classmethod
    def setUpClass(cls):
        gui_helpers.ZoneGuiTests.setUpClass()
        cls.gui = gui_helpers.ZoneGuiTests.gui

    def setUp(self):
        fixture = gui_helpers.ZoneGuiTests("test_invalid_manual_settings_are_rejected")
        fixture.setUp()
        self.app = fixture.app
        self.app.combined = True
        self.app.esp_enabled = gui_helpers.Variable(True)
        self.app.root = Scheduler()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name, "settings.json")
        self.file_patch = patch.dict(self.gui.save_settings.__globals__,
                                     {"SETTINGS_FILE": str(self.path)})
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)
        self.app._setup_live_save()

    def data(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_enable_edit_debounce_and_restore_every_panel_field(self):
        self.assertFalse(self.path.exists())
        self.app.live_save_var.set(True)
        self.assertTrue(self.data()["live_save"])
        self.app.target_var.set("distance")
        self.app.aim_button_var.set("Mouse 5")
        self.app.zone_enabled_vars["body"].set(True)
        self.app.zone_weight_vars["body"].set("40")
        self.app.head_vertical_var.set("-12")
        self.app.allow_approximate_var.set(True)
        self.app.hero_height_vars["Ivy"]["head"].set("65")
        self.app.hero_height_vars["Abrams"]["body"].set("75")
        self.app.grey_enabled.set(True)
        self.app.grey_key.set("F")
        self.app.esp_enabled.set(False)
        self.assertEqual(len(self.app.root.pending), 1)
        self.assertEqual(self.data()["target_select_type"], "fov")
        self.app.root.flush()
        data = self.data()
        self.assertEqual(data["target_select_type"], "distance")
        self.assertEqual(data["aim_button"], 9)
        self.assertTrue(data["body_enabled"])
        self.assertEqual(data["body_weight"], 40)
        self.assertEqual(data["head_vertical_offset"], -12)
        self.assertTrue(data["allow_approximate_fallback"])
        self.assertEqual(data["hero_zone_heights"], {"Ivy": {"head": 65}, "Abrams": {"body": 75}})
        self.assertTrue(data["grey_talon_lock_enabled"])
        self.assertEqual(data["grey_talon_key"], ord("F"))
        self.assertFalse(data["esp_enabled"])
        loaded = self.gui.load_saved_settings()
        self.assertTrue(loaded.live_save)
        self.assertFalse(loaded.esp_enabled)
        self.assertEqual(loaded.aim_button, 9)
        self.assertEqual(loaded.head_vertical_offset, -12)
        self.assertTrue(loaded.allow_approximate_fallback)
        self.assertEqual(loaded.hero_zone_heights, {"Ivy": {"head": 65}, "Abrams": {"body": 75}})
        self.app.live_save_status.config.assert_called_with(
            text="Live Save: saved", foreground="#9ca3af"
        )

    def test_all_zone_and_ability_settings_are_saved(self):
        self.app.live_save_var.set(True)
        self.app.random_zones_var.set(True)
        for zone, value in (("head", "30"), ("body", "50"), ("legs", "20")):
            self.app.zone_enabled_vars[zone].set(True)
            self.app.zone_weight_vars[zone].set(value)
        for name, key in (("grey", "A"), ("yamato", "B"), ("vindicta", "C")):
            getattr(self.app, f"{name}_enabled").set(True)
            getattr(self.app, f"{name}_key").set(key)
        self.app.paradox_enabled.set(True)
        self.app.paradox_r_key.set("D")
        self.app.paradox_e_key.set("E")
        self.app.root.flush()
        data = self.data()
        self.assertTrue(data["random_zones"])
        self.assertEqual([data[f"{zone}_weight"] for zone in ("head", "body", "legs")],
                         [30, 50, 20])
        self.assertTrue(all(data[f"{zone}_enabled"] for zone in ("head", "body", "legs")))
        self.assertEqual([data[f"{hero}_key"] for hero in ("grey_talon", "yamato", "vindicta")],
                         [ord("A"), ord("B"), ord("C")])
        self.assertTrue(data["paradox_shortcut_enabled"])
        self.assertEqual((data["paradox_r_key"], data["paradox_e_key"]), (ord("D"), ord("E")))

    def test_header_restores_live_and_esp_preferences(self):
        self.app.settings.live_save = True
        self.app.settings.esp_enabled = False
        self.app.root = Mock()
        with patch.object(self.gui.ttk, "Frame", create=True), \
             patch.object(self.gui.ttk, "Button", create=True):
            self.app._build_header()
        self.assertTrue(self.app.live_save_var.get())
        self.assertFalse(self.app.esp_enabled.get())

    def test_invalid_transient_edit_preserves_previous_json_then_recovers(self):
        self.app.live_save_var.set(True)
        previous = self.path.read_bytes()
        self.app.head_vertical_var.set("")
        self.app.root.flush()
        self.assertEqual(self.path.read_bytes(), previous)
        self.app.live_save_status.config.assert_called_with(
            text="Live Save: invalid settings — Head height adjustment must be an integer "
                 "from -100 to 100", foreground="#ef4444"
        )
        self.app.head_vertical_var.set("-15")
        self.app.root.flush()
        self.assertEqual(self.data()["head_vertical_offset"], -15)

    def test_toggle_off_flushes_pending_then_stops_live_writes(self):
        self.app.live_save_var.set(True)
        self.app.head_vertical_var.set("-20")
        self.assertEqual(len(self.app.root.pending), 1)
        self.app.live_save_var.set(False)
        self.assertEqual(self.data()["head_vertical_offset"], -20)
        self.assertFalse(self.data()["live_save"])
        self.assertEqual(len(self.app.root.pending), 0)
        previous = self.path.read_bytes()
        self.app.head_vertical_var.set("-25")
        self.app.root.flush()
        self.assertEqual(previous, self.path.read_bytes())

    def test_toggle_off_with_invalid_edit_remembers_preference_and_valid_data(self):
        self.app.live_save_var.set(True)
        self.app.head_vertical_var.set("")
        self.app.live_save_var.set(False)
        self.assertFalse(self.data()["live_save"])
        self.assertEqual(self.data()["head_vertical_offset"], 0)
        self.assertEqual(self.app.root.pending, {})

    def test_save_failure_keeps_previous_json_and_reports_error(self):
        self.app.live_save_var.set(True)
        previous = self.path.read_bytes()
        self.app.head_vertical_var.set("-10")
        with patch("os.replace", side_effect=PermissionError("read-only")):
            self.app.root.flush()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.glob(".aimbot-settings-*")), [])
        self.assertIn("read-only", self.app.log_queue.put.call_args.args[0])
        self.app.live_save_status.config.assert_called_with(
            text="Settings not saved; see Logs", foreground="#ef4444"
        )

    def test_closing_with_invalid_edits_warns_and_preserves_last_saved_json(self):
        self.app.live_save_var.set(True)
        previous = self.path.read_bytes()
        self.app.head_vertical_var.set("")
        self.app.is_running = False
        self.app.overlay = None
        self.app.esp_status_label = Mock()
        self.app.root.destroy = Mock()
        with patch.object(self.gui.messagebox, "showwarning") as warning:
            self.app.on_close()
        warning.assert_called_once()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(self.app.root.pending, {})

    def test_close_flushes_latest_valid_edits(self):
        self.app.live_save_var.set(True)
        self.app.head_vertical_var.set("-35")
        self.app.is_running = False
        self.app.overlay = None
        self.app.esp_status_label = Mock()
        self.app.root.destroy = Mock()
        self.app.on_close()
        self.assertEqual(self.data()["head_vertical_offset"], -35)
        self.assertEqual(self.app.root.pending, {})
        self.app.root.destroy.assert_called_once()

    def test_active_bot_receives_an_isolated_start_snapshot(self):
        self.app.live_save_var.set(True)
        self.app.hero_height_vars["Ivy"]["head"].set("65")
        self.app.esp_enabled.set(False)
        self.app.is_running = False
        self.app.bot_thread = None
        self.app.bot = None
        self.app.overlay = None
        self.app.stop_event = Mock()
        self.app.status_label = Mock()
        self.app.esp_status_label = Mock()
        self.app.esp_check = Mock()
        self.app.toggle_button = Mock()
        with patch.object(self.gui.threading, "Thread") as thread:
            self.app.start()
        run_settings = thread.call_args.kwargs["args"][0]
        self.assertEqual(run_settings.head_vertical_offset, 0)
        self.app.head_vertical_var.set("-20")
        self.app.aim_button_var.set("Mouse 5")
        self.app.allow_approximate_var.set(True)
        self.app.hero_height_vars["Ivy"]["head"].set("45")
        self.app.root.flush()
        self.assertEqual(self.data()["head_vertical_offset"], -20)
        self.assertEqual(self.data()["hero_zone_heights"]["Ivy"]["head"], 45)
        self.assertEqual(run_settings.hero_zone_heights["Ivy"]["head"], 65)
        self.assertTrue(self.app.settings.allow_approximate_fallback)
        self.assertFalse(run_settings.allow_approximate_fallback)
        self.assertEqual(self.app.settings.head_vertical_offset, -20)
        self.assertEqual(self.app.settings.aim_button, 9)
        self.assertEqual(run_settings.head_vertical_offset, 0)
        self.assertEqual(run_settings.aim_button, 8)
        self.assertIsNot(run_settings, self.app.settings)

    def test_old_settings_files_use_defaults_for_new_preferences(self):
        self.path.write_text('{"head_weight": 55}', encoding="utf-8")
        settings = self.gui.load_saved_settings()
        self.assertEqual(settings.head_weight, 55)
        self.assertEqual(settings.target_select_type, "distance")
        self.assertFalse(settings.allow_approximate_fallback)
        self.assertFalse(settings.live_save)
        self.assertTrue(settings.esp_enabled)
        self.assertEqual(settings.aim_button, 8)
        self.assertEqual(settings.hero_zone_heights, {})

    def test_invalid_saved_fallback_flag_defaults_to_strict_without_losing_settings(self):
        for value in ("true", 1, None):
            with self.subTest(value=value):
                data = {"allow_approximate_fallback": value, "head_weight": 55}
                self.path.write_text(json.dumps(data), encoding="utf-8")
                settings = self.gui.load_saved_settings()
                self.assertFalse(settings.allow_approximate_fallback)
                self.assertEqual(settings.head_weight, 55)

    def test_saved_target_selection_is_preserved_and_invalid_selection_defaults_to_distance(self):
        for choice, expected in (("fov", "fov"), ("distance", "distance"),
                                 ("invalid", "distance"), (None, "distance")):
            with self.subTest(choice=choice):
                self.path.write_text(json.dumps({"target_select_type": choice, "head_weight": 55}),
                                     encoding="utf-8")
                settings = self.gui.load_saved_settings()
                self.assertEqual(settings.target_select_type, expected)
                self.assertEqual(settings.head_weight, 55)

    def test_invalid_target_selection_preserves_last_live_save(self):
        self.app.live_save_var.set(True)
        previous = self.path.read_bytes()
        self.app.target_var.set("unknown")
        self.app.root.flush()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertIn("target selection", self.app.live_save_status.config.call_args.kwargs["text"])
        self.app.target_var.set("distance")
        self.app.root.flush()
        self.assertEqual(self.data()["target_select_type"], "distance")

    def test_invalid_saved_hero_heights_keep_other_preferences(self):
        for value in (None, {"Ivy": {"head": "65"}}, {"Unknown": {"head": 10}}):
            with self.subTest(value=value):
                self.path.write_text(json.dumps({"hero_zone_heights": value, "head_weight": 55}),
                                     encoding="utf-8")
                settings = self.gui.load_saved_settings()
                self.assertEqual(settings.hero_zone_heights, {})
                self.assertEqual(settings.head_weight, 55)

    def test_invalid_hero_height_preserves_last_live_save(self):
        self.app.live_save_var.set(True)
        previous = self.path.read_bytes()
        self.app.hero_height_vars["Ivy"]["head"].set("")
        self.app.root.flush()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertIn("Ivy head", self.app.live_save_status.config.call_args.kwargs["text"])
        self.app.hero_height_vars["Ivy"]["head"].set("65")
        self.app.root.flush()
        self.assertEqual(self.data()["hero_zone_heights"]["Ivy"]["head"], 65)

    def test_invalid_saved_button_falls_back_without_losing_other_preferences(self):
        for value in (None, "9", 7, True, 9.0):
            with self.subTest(value=value):
                data = {"aim_button": value, "head_weight": 55}
                self.path.write_text(json.dumps(data), encoding="utf-8")
                settings = self.gui.load_saved_settings()
                self.assertEqual(settings.aim_button, 8)
                self.assertEqual(settings.head_weight, 55)

    def test_invalid_button_selection_preserves_previous_snapshot(self):
        self.app.live_save_var.set(True)
        previous = self.path.read_bytes()
        self.app.aim_button_var.set("Mouse 3")
        self.app.root.flush()
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertIn("aim button", self.app.live_save_status.config.call_args.kwargs["text"])
        self.app.aim_button_var.set("Mouse 5")
        self.app.root.flush()
        self.assertEqual(self.data()["aim_button"], 9)

    def test_invalid_key_does_not_replace_valid_snapshot(self):
        self.app.live_save_var.set(True)
        previous = self.path.read_bytes()
        self.app.grey_key.set("")
        self.app.root.flush()
        self.assertEqual(self.path.read_bytes(), previous)
        self.app.grey_key.set("T")
        self.app.root.flush()
        self.assertEqual(self.data()["grey_talon_key"], ord("T"))


if __name__ == "__main__":
    unittest.main()
