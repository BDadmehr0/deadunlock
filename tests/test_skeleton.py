"""Tests for experimental name-based skeleton reads with synthetic process memory."""

import io
import math
import struct
import unittest
from unittest.mock import Mock, patch

from deadlock.aimbot import Aimbot, AimbotSettings
from deadlock.heroes import HeroIds
from deadlock.skeleton import SkeletonReader, SkeletonUnavailable
from deadlock.skeleton_diagnostics import main, report_skeleton


class FakeMemory:
    """Sparse test memory; this is not a live game process."""

    def __init__(self, names=None):
        self.data = {}
        self.pm = self
        self.close = Mock()
        self.scene, self.model, self.pose, self.names = 0x100000, 0x200000, 0x300000, 0x400000
        self.origin = (1000.0, 2000.0, 100.0)
        self.player = {"node": self.scene, "position": (1000.0, 2000.0, 170.0),
                       "hero": HeroIds.Ivy}
        self.ptr(self.scene + 0x150 + 0x80, self.pose)
        self.ptr(self.scene + 0x150 + 0xa0, 0x210000)
        self.ptr(0x210000, self.model)
        self.ptr(self.model + 0x168, self.names)
        self.set_names(names or ("pelvis", "head", "spine_2", "leg_upper_L"))

    def write(self, address, data):
        for index, byte in enumerate(data):
            self.data[address + index] = byte

    def ptr(self, address, value):
        self.write(address, struct.pack("<Q", value))

    def uint(self, address, value):
        self.write(address, struct.pack("<I", value))

    def position(self, index, point):
        self.write(self.pose + index * 32, struct.pack("<fff", *point))

    def set_names(self, names):
        self.uint(self.model + 0x170, len(names))
        for i, name in enumerate(names):
            address = 0x500000 + i * 128
            self.ptr(self.names + i * 8, address)
            self.write(address, name.encode("ascii").ljust(64, b"\0"))
            self.position(i, (1000, 2000, 140 if name == "pelvis" else 180))

    def read_bytes(self, address, count):
        try:
            return bytes(self.data[address + i] for i in range(count))
        except KeyError as exc:
            raise OSError(f"unmapped: {address:#x}") from exc

    def read_longlong(self, address):
        return struct.unpack("<Q", self.read_bytes(address, 8))[0]

    def read_uint(self, address):
        return struct.unpack("<I", self.read_bytes(address, 4))[0]

    def read_float(self, address):
        return struct.unpack("<f", self.read_bytes(address, 4))[0]

    def read_entity(self, _slot):
        return self.player


class SkeletonTests(unittest.TestCase):
    """Model resolution, safety checks and the aimbot fallback path."""

    def setUp(self):
        self.mem = FakeMemory()
        self.reader = SkeletonReader(self.mem)

    def test_lookup_is_by_name_and_uses_fresh_pose_on_every_read(self):
        head = self.reader.read(self.mem.player, "head")
        self.assertEqual((head.selected_name, head.indices["head"]), ("head", 1))
        self.assertEqual(head.positions["selected"], (1000, 2000, 180))
        self.assertEqual(self.reader.read(self.mem.player, "body").selected_name, "spine_2")
        self.assertEqual(self.reader.read(self.mem.player, "legs").selected_name, "leg_upper_l")
        self.mem.position(1, (1000, 2000, 165))
        self.assertEqual(self.reader.read(self.mem.player, "head").positions["selected"],
                         (1000, 2000, 165))
        self.assertEqual(len(self.reader._cache), 1)

    def test_new_models_can_have_different_bone_indices(self):
        other = FakeMemory(("spine_2", "head", "leg_upper_L", "pelvis"))
        other.position(3, (1000, 2000, 130))
        result = SkeletonReader(other).read(other.player, "body")
        self.assertEqual(result.indices["spine_2"], 0)
        self.assertEqual(result.indices["pelvis"], 3)

    def test_reused_model_name_array_invalidates_cached_mapping(self):
        self.reader.read(self.mem.player, "head")
        self.mem.write(0x500000 + 128, b"neck\0".ljust(64, b"\0"))
        with self.assertRaisesRegex(SkeletonUnavailable, "changed"):
            self.reader.read(self.mem.player, "head")
        self.assertFalse(self.reader._cache)
        with self.assertRaisesRegex(SkeletonUnavailable, "head and pelvis"):
            self.reader.read(self.mem.player, "head")

    def test_model_change_during_read_is_rejected(self):
        original = self.mem.read_float
        calls = 0

        def changed(address):
            nonlocal calls
            calls += 1
            value = original(address)
            if calls == 3:
                self.mem.ptr(self.mem.scene + 0x1d0, 0x600000)
            return value

        self.mem.read_float = changed
        with self.assertRaisesRegex(SkeletonUnavailable, "changed during read"):
            self.reader.read(self.mem.player, "head")
        self.assertFalse(self.reader._cache)

    def test_unsafe_or_ambiguous_data_is_rejected(self):
        cases = [
            ("null pose", lambda m: m.ptr(m.scene + 0x1d0, 0)),
            ("null handle", lambda m: m.ptr(m.scene + 0x1f0, 0)),
            ("huge count", lambda m: m.uint(m.model + 0x170, 1025)),
            ("missing pelvis", lambda m: m.set_names(("spine", "head"))),
            ("duplicate head", lambda m: m.set_names(("pelvis", "head", "head"))),
            ("zero pose", lambda m: m.position(1, (0, 0, 0))),
            ("nan pose", lambda m: m.position(1, (math.nan, 2000, 180))),
            ("far pose", lambda m: m.position(1, (9000, 2000, 180))),
            ("head below pelvis", lambda m: m.position(1, (1000, 2000, 120))),
        ]
        for name, corrupt in cases:
            with self.subTest(name=name):
                mem = FakeMemory()
                corrupt(mem)
                with self.assertRaises(SkeletonUnavailable):
                    SkeletonReader(mem).read(mem.player, "head")

    def test_unavailable_zone_does_not_guess_a_name(self):
        mem = FakeMemory(("pelvis", "head", "weapon_leg_upper_L"))
        with self.assertRaisesRegex(SkeletonUnavailable, "no recognized legs"):
            SkeletonReader(mem).read(mem.player, "legs")

    def test_aimbot_uses_named_bone_and_applies_global_head_offset(self):
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(self.mem, AimbotSettings(head_vertical_offset=-10))
        self.assertEqual(bot._automatic_target_position(self.mem.player, "head"),
                         (1000, 2000, 170))
        self.mem.ptr(self.mem.scene + 0x1d0, 0)
        with self.assertLogs("deadlock.aimbot", level="WARNING"):
            self.assertEqual(bot._automatic_target_position(self.mem.player, "head"),
                             (1000, 2000, 190))

    def test_aimbot_loop_uses_named_bone_for_target_hero(self):
        from deadlock.helpers import calculate_camera_rotation, calculate_new_camera_angles
        from deadlock.memory import EntityUnavailable

        local = {"hero": HeroIds.Abrams, "team": 2, "health": 500, "aim_angle": 0,
                 "position": (900, 2000, 170)}
        target = dict(self.mem.player, team=3, health=500)

        def entity(index):
            if index == 0:
                return local
            if index == 2:
                return target
            raise EntityUnavailable("empty")

        self.mem.read_entity = Mock(side_effect=entity)
        self.mem.camera_position = Mock(return_value=(900, 2000, 170))
        self.mem.current_angles = Mock(return_value=(0, 0))
        self.mem.set_angles = Mock()
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(self.mem)
        bot.input.button_down.side_effect = lambda button: button == 8
        with patch("deadlock.aimbot.time.sleep", side_effect=lambda _: bot.stop()):
            bot.run()
        yaw, pitch = calculate_camera_rotation((900, 2000, 170), (1000, 2000, 180))
        expected = calculate_new_camera_angles(0, 0, yaw, -pitch, 5.0)
        self.mem.set_angles.assert_called_once_with(*expected, 0)

    def test_failed_zone_retry_does_not_block_other_zones(self):
        mem = FakeMemory(("pelvis", "head", "spine_2"))
        with patch("deadlock.aimbot.X11Input"):
            bot = Aimbot(mem)
        with self.assertLogs("deadlock.aimbot", level="WARNING"):
            self.assertEqual(bot._automatic_target_position(mem.player, "legs"),
                             (1000, 2000, 130))
        self.assertEqual(bot._automatic_target_position(mem.player, "head"),
                         (1000, 2000, 180))

    def test_diagnostic_prints_positions_without_write_and_closes(self):
        with patch("deadlock.skeleton_diagnostics.DeadlockMemory", return_value=self.mem) as cls:
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(main(["--pid", "123", "--slot", "2", "--dump-names"]), 0)
        cls.assert_called_once_with(read_only=True, pid=123)
        self.mem.close.assert_called_once()
        text = output.getvalue()
        self.assertIn("hero=Ivy", text)
        self.assertIn("Candidates: pose=0x300000", text)
        self.assertIn("[1] head", text)
        self.assertIn("head[1]=(1000.0, 2000.0, 180.0)", text)
        self.assertIn("do NOT verify", text)

    def test_diagnostic_reports_missing_model(self):
        self.mem.ptr(self.mem.scene + 0x1d0, 0)
        output = io.StringIO()
        self.assertFalse(report_skeleton(self.mem, 0, output))
        self.assertIn("head: unavailable (invalid pose pointer)", output.getvalue())


if __name__ == "__main__":
    unittest.main()
