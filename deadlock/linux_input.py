"""Global input state and synthetic input for an X11 desktop."""

from __future__ import annotations

from Xlib import X, XK, display
from Xlib.ext import xinput, xtest


class X11Input:
    """Read global keys/buttons and send events using the XTEST extension."""

    def __init__(self) -> None:
        try:
            self.display = display.Display()
        except Exception as exc:
            raise RuntimeError("Cannot connect to X11; use an X11 session and set DISPLAY") from exc
        try:
            if not self.display.has_extension("XTEST"):
                raise RuntimeError("The X11 server does not provide the XTEST extension")
            if not self.display.has_extension("XInputExtension"):
                raise RuntimeError("Mouse 4/5 requires the XInput2 extension on the X11 server")
            version = self.display.xinput_query_version()
            if version.major_version < 2:
                raise RuntimeError("Mouse 4/5 requires XInput version 2 or newer")
            self.root = self.display.screen().root
        except Exception:
            self.display.close()
            raise

    def key_down(self, key: int) -> bool:
        """Check an ASCII letter or digit, as used by the GUI settings."""
        symbol = XK.string_to_keysym(chr(key).lower())
        code = self.display.keysym_to_keycode(symbol)
        if not code:
            return False
        keys = self.display.query_keymap()
        return bool(keys[code // 8] & (1 << (code % 8)))

    def button_down(self, button: int) -> bool:
        """Check X11 buttons 1/3 (left/right) or 8/9 (usual Mouse 4/5).

        Core X11 pointer masks stop at button 5. XInput2 reports the mapped
        button state for master pointers, including side buttons.
        """
        if button in (1, 3):
            mask = {1: X.Button1Mask, 3: X.Button3Mask}[button]
            return bool(self.root.query_pointer().mask & mask)
        if button not in (8, 9):
            raise ValueError(f"Unsupported X11 button {button}")
        devices = self.display.xinput_query_device(xinput.AllMasterDevices).devices
        for device in devices:
            if device.use != xinput.MasterPointer or not device.enabled:
                continue
            for info in device.classes:
                # python-xlib shifts the XI2 mask so state[0] represents button 1.
                if info.type == xinput.ButtonClass and len(info.state) >= button:
                    if info.state[button - 1]:
                        return True
        return False

    def button_event(self, button: int, pressed: bool) -> None:
        """Send a mouse press or release."""
        xtest.fake_input(self.display, X.ButtonPress if pressed else X.ButtonRelease, button)
        self.display.sync()

    def tap_key(self, key: int) -> None:
        """Send a key press and release for an ASCII setting."""
        code = self.display.keysym_to_keycode(XK.string_to_keysym(chr(key).lower()))
        if not code:
            raise ValueError(f"Key {chr(key)!r} is not present in the X11 keyboard map")
        xtest.fake_input(self.display, X.KeyPress, code)
        xtest.fake_input(self.display, X.KeyRelease, code)
        self.display.sync()

    def close(self) -> None:
        """Close the X11 connection."""
        self.display.close()
