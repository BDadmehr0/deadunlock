"""Tests for Linux process access, signature scanning, and X11 input."""

import ctypes
import os
import struct
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from Xlib import X

from deadlock.linux_input import X11Input
from deadlock.linux_process import LinuxProcess, Mapping, find_process
from deadlock.memory import DeadlockMemory, Offsets
from offset_finder import Signature, find_offsets


class ProcessTests(unittest.TestCase):
    """Exercise procfs access without requiring a running game."""

    def test_find_process_ignores_steam_launcher_arguments(self):
        reaper = SimpleNamespace(info={
            "pid": 10, "name": "reaper", "exe": "/steam/reaper",
            "cmdline": ["/steam/reaper", "SteamLaunch", "/game/deadlock.exe"],
        })
        game = SimpleNamespace(info={
            "pid": 11, "name": "deadlock.exe", "exe": "/wine/wine64-preloader",
            "cmdline": ["/game/deadlock.exe"],
        })
        with patch("deadlock.linux_process.psutil.process_iter", return_value=[reaper, game]):
            self.assertEqual(find_process("DEADLOCK.EXE"), 11)
        with patch("deadlock.linux_process.psutil.process_iter", return_value=[reaper]):
            with self.assertRaisesRegex(RuntimeError, "DEADUNLOCK_PID"):
                find_process("deadlock.exe")

    def test_find_process_accepts_command_executable(self):
        game = SimpleNamespace(info={
            "pid": 12, "name": "wine-preloader", "exe": "/wine/wine-preloader",
            "cmdline": ["/game/deadlock.exe", "-argument"],
        })
        with patch("deadlock.linux_process.psutil.process_iter", return_value=[game]):
            self.assertEqual(find_process("deadlock.exe"), 12)

    def test_find_process_handles_proton_windows_paths(self):
        reaper = SimpleNamespace(info={
            "pid": 1010671, "name": "reaper", "exe": "/steam/reaper",
            "cmdline": ["/steam/reaper", "SteamLaunch", "/game/deadlock.exe"],
        })
        game = SimpleNamespace(info={
            "pid": 1010844, "name": "MainThrd", "exe": "/wine/wine64-preloader",
            "cmdline": [r"S:\steamapps\common\Deadlock\game\bin\win64\deadlock.exe",
                        "-steam", "-console"],
        })
        with patch("deadlock.linux_process.psutil.process_iter", return_value=[reaper, game]):
            self.assertEqual(find_process("deadlock.exe"), 1010844)

    def test_read_write_and_close(self):
        value = ctypes.c_float(1.5)
        process = LinuxProcess(os.getpid())
        try:
            address = ctypes.addressof(value)
            self.assertAlmostEqual(process.read_float(address), 1.5)
            process.write_float(address, 3.25)
            self.assertAlmostEqual(value.value, 3.25)
            self.assertEqual(len(process.read_bytes(address, 4)), 4)
        finally:
            process.close()
            process.close()

    def test_mappings(self):
        process = LinuxProcess(os.getpid())
        try:
            executable = os.readlink('/proc/self/exe')
            maps = process.mappings(os.path.basename(executable))
            self.assertTrue(maps)
            self.assertEqual(process.module_base(os.path.basename(executable)),
                             min(m.start - m.offset for m in maps))
            with self.assertRaisesRegex(RuntimeError, 'not found'):
                process.mappings('this-module-does-not-exist.dll')
        finally:
            process.close()


class SignatureTests(unittest.TestCase):
    """Verify matching and RIP-relative arithmetic."""

    def test_scan_anonymous_proton_sections_within_pe_image(self):
        header_size = 0x1000
        images = {}
        maps = []
        # No schemasystem mapping: the unused schema signature is not required.
        for base, module in ((0x10000, "client.dll"),):
            image = bytearray(0x4000)
            image[:2] = b"MZ"
            struct.pack_into("<I", image, 0x3c, 0x80)
            image[0x80:0x84] = b"PE\0\0"
            struct.pack_into("<H", image, 0x80 + 20, 0xf0)
            struct.pack_into("<H", image, 0x80 + 24, 0x20b)
            struct.pack_into("<I", image, 0x80 + 80, len(image))
            # The signature crosses from the file-backed header into anonymous code.
            image[header_size - 2:header_size + 5] = b"\x48\x8b\x1d" + struct.pack("<i", 10)
            path = "/game/" + module
            maps.extend([
                Mapping(base, base + header_size, 0, "r--p", path),
                Mapping(base + header_size, base + 0x2000, 0, "r-xp", ""),
                Mapping(base + 0x2000, base + 0x3000, 0, "---p", ""),
                Mapping(base + 0x3000, base + 0x5000, 0, "r--p", "/other/file"),
            ])
            images[base] = image

        process = LinuxProcess.__new__(LinuxProcess)
        process.pid = 1
        process.fd = None
        process.all_mappings = lambda: maps

        def read(address, size):
            for base, image in images.items():
                if base <= address and address + size <= base + len(image):
                    return bytes(image[address - base:address - base + size])
            raise OSError("read outside test images")

        process.read_bytes = read
        base, size, regions = process.module_image("client.dll")
        self.assertEqual((base, size), (0x10000, 0x4000))
        self.assertEqual([(r.start, r.end) for r in regions], [(0x10000, 0x12000)])
        patterns = {name: ("48 8B 1D ? ? ? ?", 3, 7) for name in (
            "local_player_controller", "view_matrix", "entity_list",
            "camera_manager")}
        with patch("offset_finder.SIGNATURES", patterns):
            offsets = find_offsets(process=process)
        self.assertEqual(offsets["entity_list"], header_size - 2 + 10 + 7)
        self.assertNotIn("schema_system_interface", offsets)
        self.assertIsNone(Offsets(**offsets).schema_system_interface)

    def test_deadlock_memory_initializes_without_schema(self):
        offsets = {
            "local_player_controller": 1,
            "view_matrix": 2,
            "entity_list": 3,
            "camera_manager": 4,
        }
        process = SimpleNamespace(module_base=lambda module: 0x1000)
        with patch("deadlock.memory.find_process", return_value=123), \
             patch("deadlock.memory.LinuxProcess", return_value=process), \
             patch("offset_finder.find_offsets", return_value=offsets):
            memory = DeadlockMemory()
        self.assertEqual(memory.client_base, 0x1000)
        self.assertIsNone(memory.offsets.schema_system_interface)
        self.assertEqual(memory.offsets.entity_list, 3)
        self.assertEqual(Offsets(1, 2, 3, 4, 5).schema_system_interface, 5)

    def test_reject_invalid_pe_size(self):
        process = LinuxProcess.__new__(LinuxProcess)
        process.fd = None
        process.pid = 1
        process.all_mappings = lambda: [Mapping(0x1000, 0x2000, 0, "r--p", "/a/client.dll")]
        header = bytearray(4096)
        header[:2] = b"MZ"
        struct.pack_into("<I", header, 0x3c, 0x80)
        header[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", header, 0x80 + 20, 0xf0)
        struct.pack_into("<H", header, 0x80 + 24, 0x20b)
        struct.pack_into("<I", header, 0x80 + 80, 0xffffffff)
        process.read_bytes = lambda address, size: bytes(header[address - 0x1000:][:size])
        with self.assertRaisesRegex(RuntimeError, "Invalid PE image size"):
            process.module_image("client.dll")

    def test_wildcards_last_position_and_signed_displacement(self):
        data = b'prefix' + b'\x48\x8b\x1d' + struct.pack('<i', -5)
        self.assertEqual(Signature('48 8B 1D ? ? ? ?', 3, 7).find(data, 0), 8)
        self.assertIsNone(Signature('FF EE', 0, 2).find(data, 0))

    def test_reject_out_of_image_match_and_keep_searching(self):
        sig = Signature("48 8B 1D ? ? ? ?", 3, 7)
        data = (b"\x48\x8b\x1d" + struct.pack("<i", -200)
                + b"\x48\x8b\x1d" + struct.pack("<i", 0))
        self.assertEqual(sig.find(data, 0x1000, (0x1000, 0x2000)), 14)

    def test_scanning_chunk_boundary_and_missing_signature(self):
        boundary = 1024 * 1024
        data = bytearray(boundary + 32)
        data[boundary - 2:boundary + 5] = b'\x48\x8b\x1d' + struct.pack('<i', 10)
        patterns = {name: ('48 8B 1D ? ? ? ?', 3, 7) for name in (
            'local_player_controller', 'view_matrix', 'entity_list',
            'camera_manager')}

        class FakeProcess:
            def module_image(self, module):
                return 0x1000, len(data), [Mapping(0x1000, 0x1000 + len(data), 0, 'r-xp', module)]

            def read_bytes(self, address, size):
                return bytes(data[address - 0x1000:address - 0x1000 + size])

        with patch('offset_finder.SIGNATURES', patterns):
            offsets = find_offsets(process=FakeProcess())
            self.assertEqual(offsets['entity_list'], boundary - 2 + 10 + 7)
        patterns['entity_list'] = ('FF EE DD', 0, 3)
        with patch('offset_finder.SIGNATURES', patterns):
            with self.assertRaisesRegex(RuntimeError, 'entity_list'):
                find_offsets(process=FakeProcess())


class InputTests(unittest.TestCase):
    """Test input mapping without a live X server."""

    def test_input_state_and_events(self):
        class FakeDisplay:
            def keysym_to_keycode(self, symbol):
                return 24

            def query_keymap(self):
                keys = [0] * 32
                keys[3] = 1
                return keys

            def sync(self):
                pass

        class FakeRoot:
            def query_pointer(self):
                return type('Pointer', (), {'mask': X.Button3Mask})()

        device = X11Input.__new__(X11Input)
        device.display = FakeDisplay()
        device.root = FakeRoot()
        self.assertTrue(device.key_down(ord('Q')))
        self.assertTrue(device.button_down(3))
        self.assertFalse(device.button_down(1))
        with patch('deadlock.linux_input.xtest.fake_input') as fake:
            device.tap_key(ord('E'))
            device.button_event(1, False)
            self.assertEqual(fake.call_args_list[0].args[1:], (X.KeyPress, 24))
            self.assertEqual(fake.call_args_list[1].args[1:], (X.KeyRelease, 24))
            self.assertEqual(fake.call_args_list[2].args[1:], (X.ButtonRelease, 1))

class AimbotCleanupTests(unittest.TestCase):
    """Ensure synthetic mouse buttons are released when the loop exits."""

    def test_release_on_interrupt(self):
        from deadlock.aimbot import Aimbot

        class Input:
            def __init__(self):
                self.events = []
                self.right_checks = 0

            def button_down(self, button):
                if button == 1:
                    return False
                self.right_checks += 1
                if self.right_checks == 1:
                    return True
                raise KeyboardInterrupt()

            def button_event(self, button, pressed):
                self.events.append((button, pressed))

            def close(self):
                self.events.append('closed')

        device = Input()
        memory = SimpleNamespace(read_entity=lambda index: {"hero": None, "aim_angle": 0.0})
        with patch('deadlock.aimbot.X11Input', return_value=device):
            bot = Aimbot(memory)
        with self.assertRaises(KeyboardInterrupt):
            bot.run()
        self.assertEqual(device.events, [(1, True), (1, False), 'closed'])


if __name__ == '__main__':
    unittest.main()
