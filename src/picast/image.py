"""Image rendering: direct Kitty / iTerm2 / sixel protocols with half-block fallback.

Detection is done via environment variables (no terminal queries needed):
  Kitty protocol:  TERM=xterm-kitty/xterm-ghostty, KITTY_WINDOW_ID, TERM_PROGRAM=WezTerm/ghostty
  iTerm2 protocol: TERM_PROGRAM=iTerm.app, LC_TERMINAL=iTerm2
  Sixel protocol:  TERM=foot/foot-extra

The renderer embeds half-block art as a layout placeholder in the Rich panel,
then overwrites that region with the real protocol image as a post-frame overlay.
If the terminal only supports half-block the placeholder is the final output.
"""
from __future__ import annotations

import base64
import os
import sys
from io import BytesIO

from PIL import Image as PILImage

# ── protocol detection ────────────────────────────────────────────────────────

_protocol: str = "block"

_KITTY_TERMS = {"xterm-kitty", "xterm-ghostty"}
_KITTY_PROGRAMS = {"WezTerm", "ghostty"}
_ITERM2_PROGRAMS = {"iTerm.app"}
_SIXEL_TERMS = {"foot", "foot-extra"}

_KITTY_IMG_ID = 1  # default Kitty image ID (kept for API compat)


def _detect() -> None:
    global _protocol
    term = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")
    lc_terminal = os.environ.get("LC_TERMINAL", "")

    if (
        term in _KITTY_TERMS
        or os.environ.get("KITTY_WINDOW_ID")
        or term_program in _KITTY_PROGRAMS
    ):
        _protocol = "kitty"
    elif term_program in _ITERM2_PROGRAMS or lc_terminal == "iTerm2":
        _protocol = "iterm2"
    elif term in _SIXEL_TERMS:
        _protocol = "sixel"
    else:
        _protocol = "block"


_detect()


def protocol_name() -> str:
    return _protocol


# ── public API ────────────────────────────────────────────────────────────────

def render_frame_lines(
    image_bytes: bytes, cols: int, rows: int, kitty_id: int = _KITTY_IMG_ID
) -> list[str]:
    """Return escape-code lines for the active protocol, or [] to signal fallback.

    For Kitty/iTerm2/sixel returns a single-element list containing the full sequence.
    The renderer positions the cursor before writing it as an overlay.
    kitty_id lets callers use separate Kitty image slots (e.g. one per card).
    """
    if not image_bytes:
        return []
    if _protocol == "kitty":
        seq = _render_kitty(image_bytes, cols, rows, kitty_id)
        if seq:
            return [seq]
    elif _protocol == "iterm2":
        seq = _render_iterm2(image_bytes, cols, rows)
        if seq:
            return [seq]
    elif _protocol == "sixel":
        seq = _render_sixel(image_bytes, cols, rows)
        if seq:
            return [seq]
    return []


def render_half_block_lines(image_bytes: bytes, cols: int, rows: int) -> list[str]:
    """Render as Unicode half-block characters with true-colour ANSI codes."""
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


# ── protocol implementations ──────────────────────────────────────────────────

def _to_png(image_bytes: bytes, px: int = 256) -> bytes:
    """Decode, resize to a square, and re-encode as PNG."""
    img = PILImage.open(BytesIO(image_bytes)).convert("RGB")
    img = img.resize((px, px), PILImage.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_kitty(image_bytes: bytes, cols: int, rows: int, kitty_id: int = _KITTY_IMG_ID) -> str:
    """Kitty terminal graphics protocol — APC escape (ESC_G...ESC\\).

    Transmits the image with a=T (transmit + display). The renderer re-sends this
    sequence every frame: the per-frame ESC[2J clear deletes all stored images per
    the Kitty graphics spec (Ghostty honours this strictly), so re-placing an
    already-transmitted image with a=p is not reliable across terminals.
    """
    try:
        png = _to_png(image_bytes)
        b64 = base64.standard_b64encode(png).decode()
        chunk_size = 4096
        chunks = [b64[i : i + chunk_size] for i in range(0, len(b64), chunk_size)]
        parts: list[str] = []
        for i, chunk in enumerate(chunks):
            m = 0 if i == len(chunks) - 1 else 1
            if i == 0:
                # a=T transmit+display  f=100 PNG  q=2 quiet  i=ID  c/r cell dims
                parts.append(
                    f"\033_Ga=T,f=100,q=2,i={kitty_id},c={cols},r={rows},m={m};{chunk}\033\\"
                )
            else:
                parts.append(f"\033_Gm={m};{chunk}\033\\")
        return "".join(parts)
    except Exception:
        return ""


def _render_iterm2(image_bytes: bytes, cols: int, rows: int) -> str:
    """iTerm2 inline image protocol — OSC 1337."""
    try:
        png = _to_png(image_bytes)
        b64 = base64.standard_b64encode(png).decode()
        return (
            f"\033]1337;File=inline=1;width={cols};height={rows};"
            f"preserveAspectRatio=1:{b64}\a"
        )
    except Exception:
        return ""


def _get_cell_pixels() -> tuple[int, int]:
    """Return (cell_width_px, cell_height_px) via TIOCGWINSZ, or a sensible default."""
    try:
        import fcntl
        import struct
        import termios
        data = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
        _rows, _cols, xpix, ypix = struct.unpack("HHHH", data)
        if _cols > 0 and _rows > 0 and xpix > 0 and ypix > 0:
            return xpix // _cols, ypix // _rows
    except Exception:
        pass
    return 8, 16


def _render_sixel(image_bytes: bytes, cols: int, rows: int) -> str:
    """DECSIXEL sequence sized to cols×rows terminal cells.

    Pixel dimensions are derived from the terminal's reported cell size so the
    image fills the reserved card area exactly regardless of font size.
    """
    try:
        cell_w, cell_h = _get_cell_pixels()
        px_w = cols * cell_w
        px_h = rows * cell_h

        img = PILImage.open(BytesIO(image_bytes)).convert("RGB")
        img = img.resize((px_w, px_h), PILImage.LANCZOS)
        img_p = img.quantize(colors=256, dither=0)
        palette = img_p.getpalette() or ([0] * 768)
        width, height = img_p.size
        pixels = img_p.load()

        buf: list[str] = ["\033Pq"]

        # Color table: all 256 slots (unused entries are black — harmless)
        for i in range(256):
            r = palette[i * 3] * 100 // 255
            g = palette[i * 3 + 1] * 100 // 255
            b = palette[i * 3 + 2] * 100 // 255
            buf.append(f"#{i};2;{r};{g};{b}")

        # Encode 6-row bands
        for band_y in range(0, height, 6):
            band_h = min(6, height - band_y)

            # Build per-color column bitmasks for this band
            color_cols: dict[int, list[int]] = {}
            for x in range(width):
                for dy in range(band_h):
                    c = pixels[x, band_y + dy]
                    if c not in color_cols:
                        color_cols[c] = [0] * width
                    color_cols[c][x] |= 1 << dy

            # Emit each color's row with RLE, separated by CR ($)
            first = True
            for ci, col_bits in color_cols.items():
                if not first:
                    buf.append("$")
                first = False
                buf.append(f"#{ci}")
                x = 0
                while x < width:
                    run = 1
                    while x + run < width and col_bits[x + run] == col_bits[x]:
                        run += 1
                    char = chr(63 + col_bits[x])
                    buf.append(f"!{run}{char}" if run >= 4 else char * run)
                    x += run

            if band_y + 6 < height:
                buf.append("-")  # GNL: advance to next band

        buf.append("\033\\")
        return "".join(buf)
    except Exception:
        return ""
