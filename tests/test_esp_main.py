"""Test the ESP entry point without loading native Qt libraries."""

import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class ESPMainTests(unittest.TestCase):
    """Ensure the ESP uses and closes a read-only game handle."""

    def test_esp_opens_read_only_memory(self):
        qt = types.ModuleType("PyQt5")
        core = types.ModuleType("PyQt5.QtCore")
        gui = types.ModuleType("PyQt5.QtGui")
        widgets = types.ModuleType("PyQt5.QtWidgets")
        core.Qt, core.QTimer = Mock(), Mock()
        gui.QColor, gui.QPainter, gui.QPen = Mock(), Mock(), Mock()
        widgets.QApplication = Mock()
        widgets.QWidget = type("QWidget", (), {})
        modules = {"PyQt5": qt, "PyQt5.QtCore": core, "PyQt5.QtGui": gui,
                   "PyQt5.QtWidgets": widgets}
        with patch.dict(sys.modules, modules):
            esp = importlib.import_module("deadlock.esp")
        memory = Mock()
        app = Mock()
        app.platformName.return_value = "xcb"
        with patch.object(esp, "configure_overlay_display", return_value=False), \
             patch.object(esp, "QApplication", return_value=app), \
             patch.object(esp, "DeadlockMemory", return_value=memory) as open_memory, \
             patch.object(esp, "ESP") as overlay:
            esp.main([])
        open_memory.assert_called_once_with(read_only=True)
        overlay.return_value.run.assert_called_once()
        memory.pm.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
