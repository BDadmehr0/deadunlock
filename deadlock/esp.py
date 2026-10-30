"""Transparent, click-through X11 overlay for player bone positions."""

from __future__ import annotations

import argparse
import logging
import os
import sys

import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from . import mem_offsets as mo
from .display_config import configure_overlay_display
from .helpers import world_to_screen
from .memory import DeadlockMemory

logger = logging.getLogger(__name__)


class ESP(QWidget):
    """Fullscreen translucent overlay; requires an X11 compositor."""

    def __init__(self, mem: DeadlockMemory) -> None:
        """Create the overlay bound to ``mem``."""
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool | Qt.WindowTransparentForInput)
        self.mem = mem
        self.points = []
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(16)

    def refresh(self) -> None:
        """Read the current view matrix and visible player bones."""
        try:
            raw = self.mem.pm.read_bytes(self.mem.client_base + self.mem.offsets.view_matrix, 64)
            matrix = np.frombuffer(raw, dtype="<f4").reshape(4, 4)
            points = []
            for i in range(1, 16):
                try:
                    data = self.mem.read_entity(i)
                    bone_array = self.mem.read_longlong(data["node"] + mo.BONE_ARRAY)
                    for b in range(64):
                        addr = bone_array + b * mo.BONE_STEP
                        position = tuple(self.mem.read_float(addr + j * 4) for j in range(3))
                        point = world_to_screen(matrix, position, self.width(), self.height())
                        if point:
                            points.append((b, point))
                except (OSError, ValueError, KeyError):
                    logger.debug("Failed to read entity %d", i, exc_info=True)
            self.points = points
            self.update()
        except (OSError, ValueError):
            logger.exception("Failed to update overlay")
            self.close()

    def paintEvent(self, event) -> None:
        """Draw the last captured points onto the transparent window."""
        painter = QPainter(self)
        painter.setPen(QPen(QColor(255, 0, 0), 3))
        for index, (x, y) in self.points:
            x, y = int(x), int(y)
            painter.drawPoint(x, y)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(x, y - 10, str(index))
            painter.setPen(QPen(QColor(255, 0, 0), 3))
        painter.end()

    def run(self) -> None:
        """Show the overlay and run Qt's event loop."""
        self.show()
        QApplication.instance().exec_()


def main(argv: list[str] | None = None) -> None:
    """Run the overlay on an X11 desktop."""
    parser = argparse.ArgumentParser(description="Deadlock ESP overlay")
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
    if configure_overlay_display(os.environ):
        logger.warning(
            "Xwayland is experimental: global input, overlay stacking, and transparency "
            "depend on the compositor. An X11 session is recommended."
        )
    app = QApplication(sys.argv[:1])
    if app.platformName() != "xcb":
        raise RuntimeError("The overlay requires an X11 session (Qt xcb platform)")
    mem = DeadlockMemory()
    try:
        ESP(mem).run()
    finally:
        mem.pm.close()


if __name__ == "__main__":
    main()
