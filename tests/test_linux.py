"""Tests for Linux process access, signature scanning, and X11 input."""

import ctypes
import os
import struct
import unittest
from unittest.mock import patch

from Xlib import X

from deadlock.linux_input import X11Input
from deadlock.linux_process import LinuxProcess, Mapping
from offset_finder import Signature, find_offsets


class ProcessTests(unittest.TestCase):
    """Exercise procfs access without requiring a running game."""

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

    def test_wildcards_last_position_and_signed_displacement(self):
        data = b'prefix' + b'\x48\x8b\x1d' + struct.pack('<i', -5)
        self.assertEqual(Signature('48 8B 1D ? ? ? ?', 3, 7).find(data, 0), 8)
        self.assertIsNone(Signature('FF EE', 0, 2).find(data, 0))

    def test_scanning_chunk_boundary_and_missing_signature(self):
        boundary = 1024 * 1024
        data = bytearray(boundary + 32)
        data[boundary - 2:boundary + 5] = b'\x48\x8b\x1d' + struct.pack('<i', 10)
        patterns = {name: ('48 8B 1D ? ? ? ?', 3, 7) for name in (
            'local_player_controller', 'view_matrix', 'entity_list',
            'camera_manager', 'schema_system_interface')}

        class FakeProcess:
            def mappings(self, module):
                return [Mapping(0x1000, 0x1000 + len(data), 0, 'r-xp', module)]

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
        with patch('deadlock.aimbot.X11Input', return_value=device):
            bot = Aimbot(None)
        with self.assertRaises(KeyboardInterrupt):
            bot.run()
        self.assertEqual(device.events, [(1, True), (1, False), 'closed'])


if __name__ == '__main__':
    unittest.main()
