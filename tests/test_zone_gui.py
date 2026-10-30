"""Headless tests of aim-zone GUI state and validation."""

import importlib
import sys
import types
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


if __name__ == "__main__":
    unittest.main()
