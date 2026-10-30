"""Small, dependency-free text layouts with optional terminal colors."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from textwrap import wrap
from typing import TextIO

_STYLES = {
    "title": "1;36",
    "heading": "1;36",
    "muted": "2",
    "strong": "1",
    "success": "32",
    "best": "1;32",
    "warning": "33",
    "error": "31",
}


def _enable_windows_ansi(stream: TextIO) -> bool:
    """Enable VT processing on Windows consoles; leave other terminals alone."""
    if sys.platform != "win32":
        return True
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetConsoleMode.restype = wintypes.BOOL
        kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.SetConsoleMode.restype = wintypes.BOOL
        mode = wintypes.DWORD()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (OSError, ValueError):
        return False


def color_enabled(mode: str, stream: TextIO | None) -> bool:
    """Auto color is for capable terminals; explicit options override NO_COLOR.

    A None stream represents an output file. Only ``always`` colors files or
    pipes. JSON/CSV callers bypass styling entirely.
    """
    if mode == "never":
        return False
    if mode == "auto" and (os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb"):
        return False
    if stream is None or not stream.isatty():
        return mode == "always"
    supported = _enable_windows_ansi(stream)
    return mode == "always" or supported


def status_style(status: str) -> str:
    if status in ("complete", "compared"):
        return "success"
    return "error" if status == "incomparable" else "warning"


@dataclass(frozen=True)
class Cell:
    text: str
    style: str = ""


@dataclass(frozen=True)
class Console:
    """Render plain text first, then color it without changing visible widths.

    An explicit width switches oversized tables to stacked rows. None keeps
    full-width tables for redirected reports and programmatic callers.
    ASCII separators work with legacy Windows encodings as well as UTF-8.
    """

    color: bool = False
    width: int | None = None

    def paint(self, text: str, style: str = "") -> str:
        if not self.color or not style:
            return text
        return f"\x1b[{_STYLES[style]}m{text}\x1b[0m"

    def paragraph(self, text: str, style: str = "", *, indent: int = 0) -> list[str]:
        return [
            self.paint(line, style)
            for line in wrap(
                text,
                width=max(indent + 1, self.width or 100),
                initial_indent=" " * indent,
                subsequent_indent=" " * indent,
                break_on_hyphens=False,
            )
        ]

    def rule(self, length: int = 72) -> str:
        return self.paint("-" * min(length, self.width or length), "muted")

    def title(self, subtitle: str) -> list[str]:
        return [*self.paragraph(f"SEARCH ALGOS / {subtitle}", "title"), self.rule(), ""]

    def table(
        self, headers: tuple[str, ...], rows: list[list[Cell]], *, right: tuple[int, ...] = ()
    ) -> list[str]:
        widths = [
            max(len(header), *(len(row[index].text) for row in rows)) if rows else len(header)
            for index, header in enumerate(headers)
        ]
        table_width = sum(widths) + 2 * (len(headers) - 1)
        if self.width is not None and table_width > self.width:
            return self._stacked_rows(headers, rows)

        def line(cells: list[Cell]) -> str:
            fragments = []
            for index, cell in enumerate(cells):
                value = cell.text
                if index in right:
                    value = value.rjust(widths[index])
                elif index < len(cells) - 1:
                    value = value.ljust(widths[index])
                fragments.append(self.paint(value, cell.style))
            return "  ".join(fragments)

        return [
            line([Cell(header, "strong") for header in headers]),
            self.rule(table_width),
            *(line(row) for row in rows),
        ]

    def _stacked_rows(self, headers: tuple[str, ...], rows: list[list[Cell]]) -> list[str]:
        lines: list[str] = []
        width = self.width or 100
        for row in rows:
            if lines:
                lines.append("")
            lines.extend(self.paragraph(row[0].text, row[0].style or "strong"))
            current = "  "
            visible = 2
            for header, cell in zip(headers[1:], row[1:]):
                label = f"{header}: "
                length = len(label) + len(cell.text)
                separator = "  |  " if visible > 2 else ""
                if visible + len(separator) + length > width:
                    if visible > 2:
                        lines.append(current)
                    current, visible, separator = "  ", 2, ""
                if length + 2 > width:
                    lines.extend(self.paragraph(label + cell.text, cell.style, indent=2))
                    continue
                current += self.paint(separator + label, "muted") + self.paint(
                    cell.text, cell.style
                )
                visible += len(separator) + length
            if visible > 2:
                lines.append(current)
        return lines
