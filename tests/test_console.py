"""Terminal detection, Windows support, and lossless responsive formatting."""

import io
import os
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from search_algos.console import Cell, Console, _enable_windows_ansi, color_enabled


class ConsoleTests(unittest.TestCase):
    def test_auto_detects_tty_and_honors_no_color_and_dumb_terminals(self):
        stream = io.StringIO()
        with patch("search_algos.console._enable_windows_ansi", return_value=True):
            for tty in (False, True):
                for environment, allowed in (
                    ({}, True),
                    ({"NO_COLOR": ""}, True),
                    ({"NO_COLOR": "1"}, False),
                    ({"NO_COLOR": "0"}, False),
                    ({"TERM": "dumb"}, False),
                    ({"TERM": "xterm-256color"}, True),
                ):
                    with (
                        self.subTest(tty=tty, environment=environment),
                        patch.dict(os.environ, environment, clear=True),
                        patch.object(stream, "isatty", return_value=tty),
                    ):
                        self.assertEqual(color_enabled("auto", stream), tty and allowed)
                        self.assertTrue(color_enabled("always", stream))
                        self.assertFalse(color_enabled("never", stream))
                        self.assertFalse(color_enabled("auto", None))
                        self.assertTrue(color_enabled("always", None))
                        self.assertFalse(color_enabled("never", None))

    def test_unsupported_terminal_stays_plain_unless_explicitly_forced(self):
        stream = io.StringIO()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(stream, "isatty", return_value=True),
            patch("search_algos.console._enable_windows_ansi", return_value=False),
        ):
            self.assertFalse(color_enabled("auto", stream))
            self.assertTrue(color_enabled("always", stream))

    def test_windows_enables_vt_without_losing_existing_console_mode_flags(self):
        kernel = Mock()

        def get_mode(handle, pointer):
            pointer._obj.value = 0x0001
            return 1

        kernel.GetConsoleMode.side_effect = get_mode
        kernel.SetConsoleMode.return_value = 1
        stream = Mock()
        stream.fileno.return_value = 1
        msvcrt = SimpleNamespace(get_osfhandle=Mock(return_value=123))
        with (
            patch("sys.platform", "win32"),
            patch.dict(sys.modules, {"msvcrt": msvcrt}),
            patch("ctypes.WinDLL", return_value=kernel, create=True),
        ):
            self.assertTrue(_enable_windows_ansi(stream))
            kernel.SetConsoleMode.assert_called_once_with(123, 0x0005)
            kernel.SetConsoleMode.return_value = 0
            self.assertFalse(_enable_windows_ansi(stream))
            kernel.GetConsoleMode.side_effect = None
            kernel.GetConsoleMode.return_value = 0
            self.assertFalse(_enable_windows_ansi(stream))
            msvcrt.get_osfhandle.side_effect = OSError("not a console handle")
            self.assertFalse(_enable_windows_ansi(stream))

    def test_non_windows_terminals_need_no_console_mode_changes(self):
        with patch("sys.platform", "linux"):
            self.assertTrue(_enable_windows_ansi(io.StringIO()))

    def test_compact_layout_keeps_long_values_and_colors_do_not_change_alignment(self):
        rows = [
            [Cell("custom_algorithm", "best"), Cell("x" * 100), Cell("1.00x", "success")],
            [Cell("other_algorithm"), Cell("short"), Cell("0.25x", "error")],
        ]
        for width in (40, 80, 200, None):
            with self.subTest(width=width):
                plain = "\n".join(
                    Console(width=width).table(("algorithm", "value", "ratio"), rows, right=(2,))
                )
                styled = "\n".join(
                    Console(color=True, width=width).table(
                        ("algorithm", "value", "ratio"), rows, right=(2,)
                    )
                )
                self.assertEqual(re.sub(r"\x1b\[[0-9;]*m", "", styled), plain)
                self.assertEqual(plain.count("x"), 102)
                self.assertIn("other_algorithm", plain)
                self.assertIn("0.25x", plain)
                if width:
                    self.assertLessEqual(max(map(len, plain.splitlines())), width)


if __name__ == "__main__":
    unittest.main()
