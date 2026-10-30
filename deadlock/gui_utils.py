"""GUI helper classes and functions for DeadUnlock."""

from __future__ import annotations

import json
import os
import sys
import subprocess
import tempfile
import time
import logging
import queue
import threading
import tkinter as tk
from dataclasses import asdict
from tkinter import scrolledtext, ttk, messagebox

from .aimbot import AimbotSettings, validate_hero_zone_heights

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(__file__)

SETTINGS_FILE = os.path.join(BASE_DIR, "aimbot_settings.json")


def load_saved_settings() -> AimbotSettings:
    """Return stored :class:`AimbotSettings` or defaults."""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        settings = AimbotSettings(**data)
        if settings.target_select_type not in ("distance", "fov"):
            settings.target_select_type = "distance"
        if type(settings.allow_approximate_fallback) is not bool:
            settings.allow_approximate_fallback = False
        if type(settings.aim_button) is not int or settings.aim_button not in (8, 9):
            settings.aim_button = 8
        try:
            validate_hero_zone_heights(settings.hero_zone_heights)
        except ValueError:
            settings.hero_zone_heights = {}
        return settings
    except Exception:
        return AimbotSettings()


def save_settings(settings: AimbotSettings) -> None:
    """Atomically persist settings, leaving the previous JSON intact on failure.

    Raises an exception on write failure so the GUI can report it.
    """
    directory = os.path.dirname(os.path.abspath(SETTINGS_FILE))
    fd, temporary = tempfile.mkstemp(prefix=".aimbot-settings-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(settings), fh, indent=2)
            fh.write("\n")
        os.replace(temporary, SETTINGS_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def get_build_sha() -> str:
    """Return the short commit SHA for the current build."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if getattr(sys, "frozen", False):
            version_file = os.path.join(getattr(sys, "_MEIPASS", root), "version.txt")
            if os.path.exists(version_file):
                with open(version_file, "r", encoding="utf-8") as fh:
                    version = fh.read().strip()
                return version[:7] if version else "unknown"
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL
        ).decode().strip()[:7] or "unknown"
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return "unknown"


class GUILogHandler(logging.Handler):
    """Simple log handler that forwards records to a queue."""

    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            pass



