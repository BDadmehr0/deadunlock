"""Tests for unavailable local player data and safe recovery."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deadlock import mem_offsets as mo
from deadlock.aimbot import Aimbot
from deadlock.heroes import HeroIds
from deadlock.memory import DeadlockMemory, EntityUnavailable, Offsets


class PlayerMemoryTests(unittest.TestCase):
    """Validate player data before using it."""

    def test_unknown_hero_never_reads_scene_data(self):
        memory = DeadlockMemory.__new__(DeadlockMemory)
        memory.get_entity_base = Mock(return_value=(0x5000, 0x8000))
        memory.read_int = Mock(return_value=0)
        memory.read_longlong = Mock()
        with self.assertRaisesRegex(EntityUnavailable, "Unknown hero ID 0 for player 0"):
            memory.read_entity(0)
        memory.read_int.assert_called_once_with(0x5000 + mo.HERO_ID_OFFSET)
        memory.read_longlong.assert_not_called()

    def test_unknown_nonzero_hero_is_not_fabricated(self):
        memory = DeadlockMemory.__new__(DeadlockMemory)
        memory.get_entity_base = Mock(return_value=(0x5000, 0x8000))
        memory.read_int = Mock(return_value=999)
        with self.assertRaisesRegex(EntityUnavailable, "Unknown hero ID 999"):
            memory.read_entity(1)

    def test_observed_wraith_id_is_read_from_updated_offset(self):
        memory = DeadlockMemory.__new__(DeadlockMemory)
        memory.get_entity_base = Mock(return_value=(0x5000, 0x8000))
        values = {0x5000 + 0x924: 7, 0x5000 + mo.TEAM_OFFSET: 2,
                  0x8000 + mo.HEALTH_OFFSET: 500}
        memory.read_int = Mock(side_effect=values.__getitem__)
        memory.read_longlong = Mock(return_value=0x9000)
        memory.read_float = Mock(return_value=0.0)
        self.assertEqual(memory.read_entity(1)["hero"], HeroIds.Wraith)
        self.assertIn((0x5000 + 0x924,), [call.args for call in memory.read_int.call_args_list])

    def test_local_controller_does_not_read_unused_entity_slot(self):
        memory = DeadlockMemory.__new__(DeadlockMemory)
        memory.client_base = 0x100000
        memory.offsets = Offsets(0x10, 0, 0x20, 0)
        pointers = {
            0x100020: 0x4000,  # entity list
            0x100010: 0x5000,  # local controller
            0x5874: 5,  # pawn handle
            0x4010: 0x7000,  # pawn list entry
            0x7000 + 0x78 * 5: 0x8000,
        }
        memory.pm = SimpleNamespace(read_longlong=Mock(side_effect=pointers.__getitem__))
        self.assertEqual(memory.get_entity_base(0), (0x5000, 0x8000))
        self.assertEqual(memory.pm.read_longlong.call_args_list[0].args, (0x100020,))
        self.assertEqual(memory.pm.read_longlong.call_args_list[1].args, (0x100010,))
        self.assertEqual(memory.pm.read_longlong.call_count, 5)

    def test_null_pointer_has_clear_error(self):
        memory = DeadlockMemory.__new__(DeadlockMemory)
        memory.client_base = 0x100000
        memory.offsets = Offsets(0x10, 0, 0x20, 0)
        memory.pm = SimpleNamespace(read_longlong=Mock(return_value=0))
        with self.assertRaisesRegex(EntityUnavailable, "Entity list pointer is null"):
            memory.get_entity_base(0)
        self.assertEqual(memory.pm.read_longlong.call_count, 1)


class PlayerLoopTests(unittest.TestCase):
    """Avoid writes and repeated tracebacks while the local player is invalid."""

    def test_unavailable_local_player_waits_without_injecting_input(self):
        memory = SimpleNamespace(
            read_entity=Mock(side_effect=EntityUnavailable("Unknown hero ID 0")),
            set_angles=Mock(),
        )
        device = Mock()
        device.button_down.return_value = False
        with patch("deadlock.aimbot.X11Input", return_value=device):
            bot = Aimbot(memory)
        bot.locked_on = 4
        bot.force_aim_until = 123
        bot._paradox_next_e = 123
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                bot.stop()

        with patch("deadlock.aimbot.time.sleep", side_effect=sleep):
            with self.assertLogs("deadlock.aimbot", level="WARNING") as logs:
                bot.run()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("Unknown hero ID 0", logs.output[0])
        self.assertEqual(waits, [0.5, 0.5])
        self.assertIsNone(bot.locked_on)
        self.assertEqual(bot.force_aim_until, 0)
        self.assertEqual(bot._paradox_next_e, 0)
        memory.set_angles.assert_not_called()
        device.button_event.assert_not_called()
        device.tap_key.assert_not_called()
        device.close.assert_called_once()

    def test_recovery_logs_once_and_reads_valid_player(self):
        memory = SimpleNamespace(read_entity=Mock(side_effect=[
            EntityUnavailable("Unknown hero ID 0"),
            {"hero": HeroIds.Abrams, "aim_angle": 0.0},
        ]))
        device = Mock()
        device.button_down.return_value = False
        with patch("deadlock.aimbot.X11Input", return_value=device):
            bot = Aimbot(memory)
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                bot.stop()

        with patch("deadlock.aimbot.time.sleep", side_effect=sleep):
            with self.assertLogs("deadlock.aimbot", level="INFO") as logs:
                bot.run()
        self.assertEqual(sum("Local player unavailable" in line for line in logs.output), 1)
        self.assertEqual(sum("available again" in line for line in logs.output), 1)
        self.assertEqual(memory.read_entity.call_count, 2)
        device.close.assert_called_once()

    def test_synthetic_button_released_if_local_player_becomes_invalid(self):
        memory = SimpleNamespace(read_entity=Mock(side_effect=[
            {"hero": HeroIds.Abrams, "aim_angle": 0.0},
            EntityUnavailable("Unknown hero ID 0"),
        ]))
        device = Mock()
        device.button_down.side_effect = lambda button: button == 3
        with patch("deadlock.aimbot.X11Input", return_value=device):
            bot = Aimbot(memory)
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 2:
                bot.stop()

        with patch("deadlock.aimbot.time.sleep", side_effect=sleep):
            with self.assertLogs("deadlock.aimbot", level="WARNING"):
                bot.run()
        self.assertEqual([call.args for call in device.button_event.call_args_list],
                         [(1, True), (1, False)])
        device.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
