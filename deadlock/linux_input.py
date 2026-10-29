"""Global input state and synthetic input for an X11 desktop."""

from __future__ import annotations

from Xlib import X, XK, display
from Xlib.ext import xtest


class X11Input:
    """Read global keys/buttons and send events using the XTEST extension."""

    def __init__(self) -> None:
        try:
            self.display = display.Display()
        except Exception as exc:
            raise RuntimeError("Cannot connect to X11; use an X11 session and set DISPLAY") from exc
        if not self.display.has_extension("XTEST"):
            self.display.close()
            raise RuntimeError("The X11 server does not provide the XTEST extension")
        self.root = self.display.screen().root

    def key_down(self, key: int) -> bool:
        """Check an ASCII letter or digit, as used by the GUI settings."""
        symbol = XK.string_to_keysym(chr(key).lower())
        code = self.display.keysym_to_keycode(symbol)
        if not code:
            return False
        keys = self.display.query_keymap()
        return bool(keys[code // 8] & (1 << (code % 8)))

    def button_down(self, button: int) -> bool:
        """Check the X11 button number (1 left, 3 right)."""
        mask = {1: X.Button1Mask, 3: X.Button3Mask}[button]
        return bool(self.root.query_pointer().mask & mask)

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
