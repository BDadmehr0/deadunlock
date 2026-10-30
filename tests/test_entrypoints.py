"""Tests for starting without update notifications or network checks."""

import unittest
from unittest.mock import Mock, patch

from deadlock import aimbot


class EntrypointTests(unittest.TestCase):
    """The CLI must start and release resources without opening update pages."""

    def test_cli_starts_without_network_or_browser(self):
        memory, bot = Mock(), Mock()
        with patch.object(aimbot, "DeadlockMemory", return_value=memory) as open_memory, \
             patch.object(aimbot, "Aimbot", return_value=bot) as create_bot, \
             patch("socket.create_connection") as network, \
             patch("webbrowser.open") as browser:
            aimbot.main([])
        open_memory.assert_called_once_with()
        create_bot.assert_called_once_with(memory)
        bot.run.assert_called_once()
        memory.pm.close.assert_called_once()
        network.assert_not_called()
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
