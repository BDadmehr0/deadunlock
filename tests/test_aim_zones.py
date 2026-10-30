"""Tests for weighted and random aim-zone configuration."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deadlock.aimbot import Aimbot, AimbotSettings


class ZoneSettingsTests(unittest.TestCase):
    """Validate weights, zone choices, and compatibility with saved settings."""

    def test_manual_weights_use_only_enabled_positive_zones(self):
        settings = AimbotSettings(head_weight=70, body_enabled=True, body_weight=20,
                                  legs_enabled=True, legs_weight=0)
        self.assertEqual(settings.zone_weights(), {"head": 70, "body": 20})
        for settings in (AimbotSettings(head_enabled=False), AimbotSettings(head_weight=0),
                         AimbotSettings(head_weight=-1), AimbotSettings(head_weight=101),
                         AimbotSettings(head_weight=1.5)):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                settings.zone_weights()

    def test_weighted_selection_is_cached_and_respects_weights(self):
        settings = AimbotSettings(head_weight=70, body_enabled=True, body_weight=20,
                                  legs_enabled=True, legs_weight=10)
        with patch("deadlock.aimbot.X11Input"), \
             patch("deadlock.aimbot.random.choices", side_effect=[["head"], ["legs"]]) as choice:
            bot = Aimbot(Mock(), settings)
            with patch("deadlock.aimbot.time.monotonic", side_effect=[1, 1.1, 1.5]):
                self.assertEqual([bot._select_zone() for _ in range(3)],
                                 ["head", "head", "legs"])
            self.assertEqual(choice.call_count, 2)
            self.assertEqual(choice.call_args.kwargs["weights"], [70, 20, 10])

    def test_random_mode_uses_fresh_weights_for_all_zones_without_overwriting_manual(self):
        settings = AimbotSettings(random_zones=True, head_weight=95, body_enabled=False)
        with patch("deadlock.aimbot.X11Input"), \
             patch("deadlock.aimbot.random.randint", side_effect=[10, 30, 60, 1, 2, 3]):
            first, second = Aimbot(Mock(), settings), Aimbot(Mock(), settings)
        self.assertEqual(first._zone_weights, {"head": 10, "body": 30, "legs": 60})
        self.assertEqual(second._zone_weights, {"head": 1, "body": 2, "legs": 3})
        self.assertEqual(settings.head_weight, 95)
        self.assertFalse(settings.body_enabled)

    def test_each_zone_has_distinct_approximate_fallback(self):
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(SimpleNamespace(), AimbotSettings())
        target = {"position": (10, 20, 170), "node": 100}
        for zone, expected in (("head", (10, 20, 200)), ("body", (10, 20, 170)),
                               ("legs", (10, 20, 130))):
            bot._last_bad_bone_warning = float("-inf")
            with self.subTest(zone=zone), self.assertLogs("deadlock.aimbot", level="WARNING"):
                self.assertEqual(bot._target_position(target, None, zone), expected)

    def test_target_hero_fallbacks_are_independent_for_every_zone(self):
        from deadlock.heroes import HeroIds

        settings = AimbotSettings(
            head_vertical_offset=-5,
            hero_zone_heights={"Ivy": {"head": 65, "body": 44, "legs": 18},
                               "Abrams": {"head": 110}},
        )
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(SimpleNamespace(), settings)
        targets = ((HeroIds.Ivy, (160, 144, 118)),
                   (HeroIds.Abrams, (205, 170, 130)),
                   (HeroIds.Wraith, (195, 170, 130)))
        for hero, expected in targets:
            for zone, height in zip(("head", "body", "legs"), expected):
                with self.subTest(hero=hero, zone=zone):
                    target = {"hero": hero, "position": (10, 20, 170), "node": 100}
                    self.assertEqual(bot._target_position(target, None, zone), (10, 20, height))

    def test_per_hero_fallback_does_not_alter_a_plausible_bone(self):
        from deadlock.heroes import HeroIds

        memory = SimpleNamespace(read_longlong=Mock(return_value=0x4000),
                                 read_float=Mock(side_effect=[100, 200, 210]))
        settings = AimbotSettings(hero_zone_heights={"Ivy": {"head": 45}},
                                  head_vertical_offset=-10)
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(memory, settings)
        target = {"hero": HeroIds.Ivy, "position": (100, 200, 170), "node": 0x1000}
        self.assertEqual(bot._target_position(target, 7, "head"), (100, 200, 200))

    def test_invalid_hero_heights_are_rejected_before_opening_input(self):
        cases = (None, [], {"Fake": {"head": 20}}, {"Ivy": None},
                 {"Ivy": {"wing": 10}}, {"Ivy": {"head": -1}},
                 {"Ivy": {"head": 201}}, {"Ivy": {"head": 1.5}},
                 {"Ivy": {"head": True}}, {"Ivy": {"head": "100"}})
        for value in cases:
            with self.subTest(value=value), patch("deadlock.aimbot.X11Input") as x11:
                with self.assertRaises(ValueError):
                    Aimbot(Mock(), AimbotSettings(hero_zone_heights=value))
                x11.assert_not_called()

    def test_aim_loop_uses_selected_zone_when_bones_are_unavailable(self):
        from deadlock.helpers import calculate_camera_rotation, calculate_new_camera_angles
        from deadlock.heroes import HeroIds
        from deadlock.memory import EntityUnavailable

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

        for zone, height in (("head", 100), ("body", 70), ("legs", 30)):
            with self.subTest(zone=zone):
                memory = SimpleNamespace(
                    read_entity=Mock(side_effect=read_entity),
                    camera_position=Mock(return_value=(100, 100, 100)),
                    current_angles=Mock(return_value=(0, 0)),
                    read_longlong=Mock(return_value=0), set_angles=Mock(),
                )
                with patch("deadlock.aimbot.X11Input"):
                    bot = Aimbot(memory, AimbotSettings(allow_approximate_fallback=True))
                bot.input.button_down.side_effect = lambda button: button == 8
                bot._select_zone = Mock(return_value=zone)
                with patch("deadlock.aimbot.time.sleep", side_effect=lambda _: bot.stop()):
                    with self.assertLogs("deadlock.aimbot", level="WARNING"):
                        bot.run()
                yaw, pitch = calculate_camera_rotation((100, 100, 100), (200, 150, height))
                expected = calculate_new_camera_angles(0, 0, yaw, -pitch, 5.0)
                memory.set_angles.assert_called_once_with(*expected, 0)

    def test_aim_loop_uses_target_hero_height_not_local_hero(self):
        from deadlock.helpers import calculate_camera_rotation, calculate_new_camera_angles
        from deadlock.heroes import HeroIds
        from deadlock.memory import EntityUnavailable

        local = {"hero": HeroIds.Abrams, "team": 2, "health": 730, "aim_angle": 0,
                 "position": (100, 100, 70)}
        target = {"hero": HeroIds.Ivy, "team": 3, "health": 373, "node": 0x1000,
                  "position": (200, 150, 70)}

        def read_entity(slot):
            if slot == 0:
                return local
            if slot == 2:
                return target
            raise EntityUnavailable("empty")

        memory = SimpleNamespace(
            read_entity=Mock(side_effect=read_entity),
            camera_position=Mock(return_value=(100, 100, 100)),
            current_angles=Mock(return_value=(0, 0)),
            read_longlong=Mock(return_value=0), set_angles=Mock(),
        )
        settings = AimbotSettings(hero_zone_heights={"Ivy": {"head": 65},
                                                      "Abrams": {"head": 110}},
                                  allow_approximate_fallback=True)
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(memory, settings)
        bot.input.button_down.side_effect = lambda button: button == 8
        with patch("deadlock.aimbot.time.sleep", side_effect=lambda _: bot.stop()):
            with self.assertLogs("deadlock.aimbot", level="WARNING") as logs:
                bot.run()
        self.assertIn("Ivy head fallback is origin + 65", logs.output[0])
        yaw, pitch = calculate_camera_rotation((100, 100, 100), (200, 150, 65))
        expected = calculate_new_camera_angles(0, 0, yaw, -pitch, 5.0)
        memory.set_angles.assert_called_once_with(*expected, 0)

    def test_head_height_adjustment_applies_to_bone_and_fallback_only(self):
        settings = AimbotSettings(head_vertical_offset=-20, random_zones=True)
        memory = SimpleNamespace(read_longlong=Mock(return_value=0x4000), read_float=Mock())
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(memory, settings)
        target = {"position": (100, 200, 170), "node": 0x1000}
        memory.read_float.side_effect = [100, 200, 210]
        self.assertEqual(bot._target_position(target, 7, "head"), (100, 200, 190))
        with self.assertLogs("deadlock.aimbot", level="WARNING"):
            self.assertEqual(bot._target_position(target, None, "head"), (100, 200, 180))
        self.assertEqual(bot._target_position(target, None, "body"), (100, 200, 170))
        self.assertEqual(bot._target_position(target, None, "legs"), (100, 200, 130))

    def test_head_adjustment_does_not_change_bone_plausibility_check(self):
        memory = SimpleNamespace(read_longlong=Mock(return_value=0x4000),
                                 read_float=Mock(side_effect=[100, 200, 360]))
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(memory, AimbotSettings(head_vertical_offset=-100))
        target = {"position": (100, 200, 170), "node": 0x1000}
        self.assertEqual(bot._target_position(target, 7, "head"), (100, 200, 260))

    def test_bad_height_adjustments_are_rejected_before_opening_input(self):
        for value in (-101, 101, 1.5, True, "0"):
            with self.subTest(value=value), patch("deadlock.aimbot.X11Input") as x11:
                with self.assertRaisesRegex(ValueError, "Head vertical adjustment"):
                    Aimbot(Mock(), AimbotSettings(head_vertical_offset=value))
                x11.assert_not_called()

    def test_old_settings_can_be_loaded_and_new_settings_round_trip(self):
        # Avoid importing the Tk GUI helpers when Tk is unavailable in the test environment.
        from dataclasses import asdict
        old = AimbotSettings(**{"headshot_probability": 0.8, "headshot_on_acquire": False})
        self.assertEqual(old.zone_weights(), {"head": 100})
        configured = AimbotSettings(random_zones=True, body_enabled=True, body_weight=42)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps(asdict(configured)))
            restored = AimbotSettings(**json.loads(path.read_text()))
        self.assertEqual(configured, restored)


if __name__ == "__main__":
    unittest.main()
