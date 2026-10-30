"""Select the Qt X11 backend and report unsupported desktop configurations."""

from __future__ import annotations

from typing import MutableMapping


def configure_overlay_display(environment: MutableMapping[str, str]) -> bool:
    """Select xcb if unset; return whether this is a Wayland/Xwayland session.

    The caller must invoke this before creating a QApplication. Explicit
    incompatible choices are not silently overwritten.
    """
    if not environment.get("DISPLAY"):
        raise RuntimeError(
            "ESP needs an X11 DISPLAY. Log into an X11 session, or use Xwayland "
            "(experimental and compositor-dependent)."
        )
    platform = environment.get("QT_QPA_PLATFORM", "")
    if platform and platform.split(":", 1)[0].lower() != "xcb":
        raise RuntimeError(
            f"ESP requires Qt's xcb backend, not {platform!r}. Try "
            "QT_QPA_PLATFORM=xcb python -m deadlock.esp in an X11 session."
        )
    if not platform:
        environment["QT_QPA_PLATFORM"] = "xcb"
    return environment.get("XDG_SESSION_TYPE", "").lower() == "wayland"
