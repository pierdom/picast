"""Async keyboard reader using asyncio add_reader on raw-mode stdin."""
from __future__ import annotations

import asyncio
import os
import sys
import termios
import tty
from collections.abc import AsyncIterator

# Named key constants
UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
ENTER = "enter"
SPACE = "space"
ESCAPE = "escape"
TAB = "tab"
BACKSPACE = "backspace"
CTRL_C = "ctrl_c"

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
}


class KeyReader:
    """Reads keypresses from stdin in raw mode and yields named key strings."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
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
            data = os.read(sys.stdin.fileno(), 32)
        except OSError:
            return
        key = _parse(data)
        if key and self._loop:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, key)

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            yield await self._queue.get()


def _parse(data: bytes) -> str | None:
    if not data:
        return None
    if data in _ESC_MAP:
        return _ESC_MAP[data]
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
