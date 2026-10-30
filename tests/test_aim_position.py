"""Tests for aiming with unreliable player bone data."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deadlock.aimbot import Aimbot, AimbotSettings
from deadlock.helpers import calculate_camera_rotation, calculate_new_camera_angles
from deadlock.heroes import HeroIds
from deadlock.memory import EntityUnavailable


class AimPositionTests(unittest.TestCase):
    """Do not aim at invalid bones when a plausible player position is available."""

    def setUp(self):
        self.memory = SimpleNamespace(read_longlong=Mock(), read_float=Mock())
        with patch("deadlock.aimbot.X11Input"):
            self.bot = Aimbot(self.memory, AimbotSettings(allow_approximate_fallback=True))
        self.target = {"node": 0x1000, "position": (11685.875, -8528.0, -281.0625)}

    def test_nearby_bone_is_used(self):
        self.memory.read_longlong.return_value = 0x4000
        self.memory.read_float.side_effect = [11685.0, -8528.0, -260.0]
        self.assertEqual(self.bot._target_position(self.target, 7), (11685, -8528, -260))
        self.assertEqual(
            [call.args[0] for call in self.memory.read_float.call_args_list],
            [0x4000 + 7 * 32 + n for n in (0, 4, 8)],
        )

    def test_unusable_bones_fall_back_and_warn(self):
        cases = (
            (0, None),
            (0x4000, [0.0, 0.0, 0.0]),
            (0x4000, [float("nan"), 1.0, 2.0]),
            (0x4000, [900.0, 900.0, 900.0]),
            (0x4000, OSError("unreadable")),
        )
        for pointer, values in cases:
            with self.subTest(pointer=pointer, values=values):
                self.memory.read_longlong.return_value = pointer
                self.memory.read_float.side_effect = values
                self.bot._last_bad_bone_warning = float("-inf")
                with self.assertLogs("deadlock.aimbot", level="WARNING"):
                    self.assertEqual(self.bot._target_position(self.target, 7),
                                     self.target["position"])

    def test_unknown_bone_uses_fallback_without_read(self):
        with self.assertLogs("deadlock.aimbot", level="WARNING"):
            self.assertEqual(self.bot._target_position(self.target, None), self.target["position"])
        self.memory.read_longlong.assert_not_called()

    def test_loop_aims_at_centre_instead_of_zero_bone(self):
        local = {"hero": HeroIds.Wraith, "team": 2, "health": 730, "aim_angle": 0,
                 "position": (11894.5, -8691.9375, -280.96875)}
        target = dict(self.target, hero=HeroIds.Abrams, team=3, health=373)
        camera = (12001.948, -8725.047, -259.227)
        angles = (143.984, -1.0)

        def read_entity(slot):
            if slot == 0:
                return local
            if slot == 2:
                return target
            raise EntityUnavailable("empty")

        self.memory.read_entity = Mock(side_effect=read_entity)
        self.memory.camera_position = Mock(return_value=camera)
        self.memory.current_angles = Mock(return_value=angles)
        self.memory.set_angles = Mock()
        self.memory.read_longlong.return_value = 0x4000
        self.memory.read_float.return_value = 0.0
        self.bot._zone_weights = {"body": 1}
        self.bot.input.button_down.side_effect = lambda button: button == 8

        def stop_on_sleep(_seconds):
            self.bot.stop()

        with patch("deadlock.aimbot.time.sleep", side_effect=stop_on_sleep):
            with self.assertLogs("deadlock.aimbot", level="WARNING"):
                self.bot.run()

        yaw, pitch = calculate_camera_rotation(camera, target["position"])
        expected = calculate_new_camera_angles(*angles, yaw, -pitch, self.bot.settings.smooth_speed)
        self.memory.set_angles.assert_called_once_with(*expected, 0)


if __name__ == "__main__":
    unittest.main()
