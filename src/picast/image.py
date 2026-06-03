"""Image rendering: graphics protocols with half-block fallback.

Protocol detection order: Kitty → iTerm2 → Sixel → half-block.
`_detect()` is called at module load AND again from Renderer.enter_screen() so
the terminal is definitely live before we make the final decision.
"""
from __future__ import annotations

import contextlib
import io
import sys
from io import BytesIO

from PIL import Image as PILImage

# ── protocol detection ────────────────────────────────────────────────────────

_protocol: str = "block"
_ImageClass = None


def _detect() -> None:
    """Detect the best available image protocol for the current terminal."""
    global _protocol, _ImageClass
    try:
        from term_image.image import ITerm2Image, KittyImage, SixelImage

        for name, cls in [
            ("kitty", KittyImage),
            ("iterm2", ITerm2Image),
            ("sixel", SixelImage),
        ]:
            try:
                if cls.is_supported():
                    _protocol = name
                    _ImageClass = cls
                    return
            except Exception:
                continue
    except ImportError:
        pass
    _protocol = "block"
    _ImageClass = None


_detect()  # initial probe (may be outside a real terminal; re-run from enter_screen)


def protocol_name() -> str:
    return _protocol


# ── public API ────────────────────────────────────────────────────────────────

def render_frame_lines(image_bytes: bytes, cols: int, rows: int) -> list[str]:
    """Return a list of ANSI strings, one per terminal row, ready to splice into a frame.

    For graphics protocols the list has one element: the full escape sequence
    (with embedded cursor positioning). For half-block it's one line per row.
    Each entry must be written at the correct cursor position by the caller.
    """
    if not image_bytes:
        return []

    if _ImageClass is not None:
        escaped = _capture_protocol(image_bytes, cols, rows)
        if escaped:
            return [escaped]  # single blob; caller positions cursor before writing

    return render_half_block_lines(image_bytes, cols, rows)


def render_half_block_lines(image_bytes: bytes, cols: int, rows: int) -> list[str]:
    """Render as Unicode half-block characters with true-color ANSI codes."""
    try:
        pil_img = PILImage.open(BytesIO(image_bytes)).convert("RGB")
        pil_img = pil_img.resize((cols, rows * 2), PILImage.LANCZOS)
        px = pil_img.load()
        lines = []
        for r in range(rows):
            line = ""
            for c in range(cols):
                tr, tg, tb = px[c, r * 2]
                br, bg, bb = px[c, r * 2 + 1]
                line += (
                    f"\033[38;2;{tr};{tg};{tb}m"
                    f"\033[48;2;{br};{bg};{bb}m"
                    "▀\033[0m"
                )
            lines.append(line)
        return lines
    except Exception:
        return []


# ── legacy draw_at (used if anything still calls it directly) ─────────────────

def draw_at(image_bytes: bytes, row: int, col: int, cols: int, rows: int) -> None:
    """Render image at terminal position (1-indexed). Prefer render_frame_lines."""
    if not image_bytes:
        return
    lines = render_frame_lines(image_bytes, cols, rows)
    if _ImageClass is not None and len(lines) == 1:
        sys.stdout.write(f"\033[{row};{col}H")
        sys.stdout.write(lines[0])
        sys.stdout.flush()
    else:
        for i, line in enumerate(lines):
            sys.stdout.write(f"\033[{row + i};{col}H{line}")
        sys.stdout.flush()


# ── internal ──────────────────────────────────────────────────────────────────

def _capture_protocol(image_bytes: bytes, cols: int, rows: int) -> str:
    """Capture term-image's escape-code output as a string."""
    try:
        pil_img = PILImage.open(BytesIO(image_bytes))
        img = _ImageClass(pil_img)  # type: ignore[call-arg]
        img.set_size(cols, rows)   # pin to exact cell area; no aspect-ratio drift
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            img.draw()
        return buf.getvalue()
    except Exception:
        return ""
