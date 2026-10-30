"""Tests for distance-based target acquisition and lock maintenance."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deadlock.aimbot import Aimbot, AimbotSettings
from deadlock.heroes import HeroIds
from deadlock.memory import EntityUnavailable


def player(position, *, team=3, health=500):
    """Create an entity as returned by the process-memory reader."""
    return {"hero": HeroIds.Abrams, "position": position, "team": team,
            "health": health, "node": 0x1000, "aim_angle": 0}


class TargetSelectionTests(unittest.TestCase):
    """Exercise the running loop using deterministic positions and clock values."""

    def run_frames(self, frames, *, mode="distance", times=None):
        local = player((0, 0, 70), team=2)
        step = 0
        times = times or [0.2 * index for index in range(len(frames))]

        def read_entity(slot):
            if slot == 0:
                return local
            if slot not in frames[step]:
                raise EntityUnavailable("empty slot")
            return frames[step][slot]

        mem = SimpleNamespace(
            read_entity=Mock(side_effect=read_entity),
            camera_position=Mock(return_value=(0, 0, 70)),
            current_angles=Mock(return_value=(0, 0)),
            set_angles=Mock(),
        )
        device = Mock()
        device.button_down.side_effect = lambda button: button == 8
        device.key_down.return_value = False
        with patch("deadlock.aimbot.X11Input", return_value=device):
            bot = Aimbot(mem, AimbotSettings(target_select_type=mode))
        bot._select_zone = Mock(return_value="head")
        bot._automatic_target_position = Mock(side_effect=lambda target, _zone: target["position"])

        def sleep(_duration):
            nonlocal step
            step += 1
            if step >= len(frames):
                bot.stop()

        with patch("deadlock.aimbot.time.monotonic", side_effect=lambda: times[step]), \
             patch("deadlock.aimbot.time.sleep", side_effect=sleep):
            bot.run()
        return bot, mem

    def test_nearest_enemy_is_selected_in_world_space(self):
        near = player((0, 10, 70))
        far_near_crosshair = player((100, 0, 70))
        bot, mem = self.run_frames([{1: far_near_crosshair, 2: near}])
        self.assertEqual(bot.locked_on, 2)
        self.assertIs(bot._automatic_target_position.call_args.args[0], near)
        mem.set_angles.assert_called_once()

    def test_distance_includes_height_and_filters_friend_dead_and_invalid_positions(self):
        closest = player((10, 0, 70))
        frames = [{
            1: player((1, 0, 70), team=2),
            2: player((2, 0, 70), health=0),
            3: player((float("nan"), 0, 70)),
            4: player((1, 0, 170)),
            5: closest,
        }]
        bot, _ = self.run_frames(frames)
        self.assertEqual(bot.locked_on, 5)
        self.assertIs(bot._automatic_target_position.call_args.args[0], closest)

    def test_nearest_is_rechecked_periodically_while_button_is_held(self):
        initial_near = player((10, 0, 70))
        other = player((50, 0, 70))
        other_now_near = player((5, 0, 70))
        bot, _ = self.run_frames([
            {1: initial_near, 2: other},
            {1: initial_near, 2: other_now_near},
            {1: initial_near, 2: other_now_near},
        ], times=[0.0, 0.05, 0.11])
        targets = [call.args[0] for call in bot._automatic_target_position.call_args_list]
        self.assertEqual(targets, [initial_near, initial_near, other_now_near])
        self.assertEqual(bot.locked_on, 2)

    def test_empty_scan_is_throttled_until_the_next_interval(self):
        enemy = player((10, 0, 70))
        with self.assertLogs("deadlock.aimbot", level="WARNING"):
            bot, mem = self.run_frames([{}, {1: enemy}, {1: enemy}], times=[0.0, 0.05, 0.11])
        self.assertEqual(bot.locked_on, 1)
        self.assertEqual(bot._automatic_target_position.call_count, 1)
        self.assertEqual(mem.set_angles.call_count, 1)

    def test_equal_distance_keeps_the_existing_target(self):
        first = player((10, 0, 70))
        second = player((5, 0, 70))
        same_distance = player((5, 0, 70))
        bot, _ = self.run_frames([{1: first, 2: second}, {1: same_distance, 2: second}])
        self.assertEqual(bot.locked_on, 2)
        self.assertIs(bot._automatic_target_position.call_args.args[0], second)

    def test_fov_still_prioritizes_crosshair_and_keeps_lock(self):
        near = player((0, 10, 70))
        far_near_crosshair = player((100, 0, 70))
        bot, _ = self.run_frames([{1: far_near_crosshair, 2: near}] * 2, mode="fov")
        self.assertEqual(bot.locked_on, 1)
        self.assertEqual(bot._automatic_target_position.call_count, 2)

    def test_dead_locked_target_is_dropped_and_reacquired(self):
        active = player((100, 0, 70))
        dead = player((100, 0, 70), health=0)
        other = player((0, 10, 70))
        bot, mem = self.run_frames([
            {1: active, 2: other}, {1: dead, 2: other}, {1: dead, 2: other},
        ], mode="fov")
        self.assertEqual(bot.locked_on, 2)
        self.assertEqual([c.args[0] for c in bot._automatic_target_position.call_args_list],
                         [active, other])
        self.assertEqual(mem.set_angles.call_count, 2)

    def test_default_and_invalid_selection(self):
        self.assertEqual(AimbotSettings().target_select_type, "distance")
        for mode in ("", "nearest", None, 3):
            with self.subTest(mode=mode), patch("deadlock.aimbot.X11Input") as device:
                with self.assertRaisesRegex(ValueError, "Target selection"):
                    Aimbot(Mock(), AimbotSettings(target_select_type=mode))
                device.assert_not_called()


if __name__ == "__main__":
    unittest.main()
