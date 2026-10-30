"""Tests for Mouse 4 activation of the aimbot."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deadlock.aimbot import AIM_BUTTON, Aimbot, AimbotSettings
from deadlock.heroes import HeroIds
from deadlock.memory import EntityUnavailable


class MouseFourTests(unittest.TestCase):
    """Aim only while the mapped side button is held, absent ability locks."""

    def test_mouse4_and_mouse5_activate_only_selected_button(self):
        for button in (8, 9):
            with self.subTest(button=button):
                self._run_release_scenario(button)

    def test_default_and_invalid_buttons(self):
        self.assertEqual(AimbotSettings().aim_button, AIM_BUTTON)
        for value in (7, 10, True, 8.0, "9"):
            with self.subTest(value=value), patch("deadlock.aimbot.X11Input") as device:
                with self.assertRaisesRegex(ValueError, "Aim button"):
                    Aimbot(Mock(), AimbotSettings(aim_button=value))
                device.assert_not_called()

    def _run_release_scenario(self, aim_button):
        local = {"hero": HeroIds.Wraith, "team": 2, "health": 730, "aim_angle": 0,
                 "position": (100, 100, 70)}
        target = {"hero": HeroIds.Abrams, "team": 3, "health": 373, "node": 0x1000,
                  "position": (200, 150, 70)}

        def read_entity(slot):
            if slot == 0:
                return local
            if slot == 2:
                return target
            raise EntityUnavailable("empty")

        mem = SimpleNamespace(
            read_entity=Mock(side_effect=read_entity),
            camera_position=Mock(return_value=(100, 100, 100)),
            current_angles=Mock(return_value=(0, 0)),
            read_longlong=Mock(return_value=0), set_angles=Mock(),
        )
        device = Mock()
        side_states = iter((False, True, False))  # initial, first loop, second loop
        device.button_down.side_effect = lambda button: (
            next(side_states) if button == aim_button else button == 1
        )
        with patch("deadlock.aimbot.X11Input", return_value=device):
            bot = Aimbot(mem, AimbotSettings(aim_button=aim_button))
        sleeps = []

        def on_sleep(duration):
            sleeps.append(duration)
            if len(sleeps) == 2:
                bot.stop()

        with patch("deadlock.aimbot.time.sleep", side_effect=on_sleep):
            with self.assertLogs("deadlock.aimbot", level="WARNING"):
                bot.run()
        mem.set_angles.assert_called_once()
        device.button_event.assert_not_called()
        self.assertIsNone(bot.locked_on)
        self.assertEqual(sleeps, [0.001, 0.01])
        device.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
