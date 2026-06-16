"""Async keyboard reader using asyncio add_reader on raw-mode stdin."""
from __future__ import annotations

import asyncio
import os
import sys
import termios
import tty
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Named key constants
UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
ENTER = "enter"
SPACE = "space"
ESCAPE = "escape"
TAB = "tab"
BACKTAB = "backtab"   # Shift+Tab
BACKSPACE = "backspace"
CTRL_C = "ctrl_c"


@dataclass
class MouseEvent:
    action: str  # "press", "release", "scroll_up", "scroll_down"
    col: int     # 1-indexed terminal column
    row: int     # 1-indexed terminal row

# Escape sequence → name map
_ESC_MAP: dict[bytes, str] = {
    b"\x1b[A": UP,
    b"\x1b[B": DOWN,
    b"\x1b[C": RIGHT,
    b"\x1b[D": LEFT,
    b"\x1b[H": "home",
    b"\x1b[F": "end",
    b"\x1b[5~": "page_up",
    b"\x1b[6~": "page_down",
    b"\x1b[Z": BACKTAB,
}


class KeyReader:
    """Reads keypresses from stdin in raw mode and yields named key strings."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | MouseEvent] = asyncio.Queue()
        self._old_settings: list | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._old_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setraw(sys.stdin.fileno())
        loop.add_reader(sys.stdin.fileno(), self._on_readable)

    def stop(self) -> None:
        if self._loop:
            try:
                self._loop.remove_reader(sys.stdin.fileno())
            except Exception:
                pass
        if self._old_settings is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass

    def _on_readable(self) -> None:
        try:
            data = os.read(sys.stdin.fileno(), 64)
        except OSError:
            return
        key = _parse(data)
        if key is not None and self._loop:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, key)

    async def __aiter__(self) -> AsyncIterator[str | MouseEvent]:
        while True:
            yield await self._queue.get()


def _parse(data: bytes) -> str | MouseEvent | None:
    if not data:
        return None
    if data in _ESC_MAP:
        return _ESC_MAP[data]

    # SGR extended mouse: ESC [ < btn ; col ; row M/m
    if data.startswith(b"\x1b[<"):
        try:
            suffix = chr(data[-1])
            inner = data[3:-1].decode("ascii")
            parts = inner.split(";")
            btn, col, row = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, IndexError, UnicodeDecodeError):
            return None
        if btn == 64:
            return MouseEvent("scroll_up", col, row)
        if btn == 65:
            return MouseEvent("scroll_down", col, row)
        if btn == 0 and suffix == "M":
            return MouseEvent("press", col, row)
        if btn == 0 and suffix == "m":
            return MouseEvent("release", col, row)
        return None

    # X10 normal mouse: ESC [ M <btn+32> <col+32> <row+32>
    if data.startswith(b"\x1b[M") and len(data) >= 6:
        btn = data[3] - 32
        col = data[4] - 32
        row = data[5] - 32
        if btn == 64:
            return MouseEvent("scroll_up", col, row)
        if btn == 65:
            return MouseEvent("scroll_down", col, row)
        if btn == 0:
            return MouseEvent("press", col, row)
        if btn == 3:
            return MouseEvent("release", col, row)
        return None

    if data == b"\x1b":
        return ESCAPE
    if data == b"\r" or data == b"\n":
        return ENTER
    if data == b" ":
        return SPACE
    if data == b"\t":
        return TAB
    if data == b"\x7f" or data == b"\x08":
        return BACKSPACE
    if data == b"\x03":
        return CTRL_C
    if len(data) == 1 and 0x20 <= data[0] <= 0x7e:
        return data.decode("ascii")
    return None
