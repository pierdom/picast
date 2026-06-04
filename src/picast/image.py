"""Image rendering: direct Kitty / iTerm2 protocols with half-block fallback.

Detection is done via environment variables (no terminal queries needed):
  Kitty protocol: TERM=xterm-kitty, KITTY_WINDOW_ID, TERM_PROGRAM=WezTerm/ghostty
  iTerm2 protocol: TERM_PROGRAM=iTerm.app, LC_TERMINAL=iTerm2

The renderer embeds half-block art as a layout placeholder in the Rich panel,
then overwrites that region with the real protocol image as a post-frame overlay.
If the terminal only supports half-block the placeholder is the final output.
"""
from __future__ import annotations

import base64
import os
from io import BytesIO

from PIL import Image as PILImage

# ── protocol detection ────────────────────────────────────────────────────────

_protocol: str = "block"

_KITTY_TERMS = {"xterm-kitty", "xterm-ghostty"}
_KITTY_PROGRAMS = {"WezTerm", "ghostty"}
_ITERM2_PROGRAMS = {"iTerm.app"}

_KITTY_IMG_ID = 1  # fixed ID for the cover image slot


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
    else:
        _protocol = "block"


_detect()


def protocol_name() -> str:
    return _protocol


# ── public API ────────────────────────────────────────────────────────────────

def render_frame_lines(image_bytes: bytes, cols: int, rows: int) -> list[str]:
    """Return escape-code lines for the active protocol, or [] to signal fallback.

    For Kitty/iTerm2 returns a single-element list containing the full sequence.
    The renderer positions the cursor before writing it as an overlay.
    """
    if not image_bytes:
        return []
    if _protocol == "kitty":
        seq = _render_kitty(image_bytes, cols, rows)
        if seq:
            return [seq]
    elif _protocol == "iterm2":
        seq = _render_iterm2(image_bytes, cols, rows)
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
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def kitty_redisplay(cols: int, rows: int) -> str:
    """Re-place an already-transmitted Kitty image (no data transfer)."""
    return f"\033_Ga=p,q=2,i={_KITTY_IMG_ID},c={cols},r={rows}\033\\"


def kitty_delete() -> str:
    """Delete the Kitty cover image from terminal cache."""
    return f"\033_Ga=d,q=2,i={_KITTY_IMG_ID}\033\\"


def _render_kitty(image_bytes: bytes, cols: int, rows: int) -> str:
    """Kitty terminal graphics protocol — APC escape (ESC_G...ESC\\).

    Transmits the image with a fixed ID so subsequent frames can use
    kitty_redisplay() instead of retransmitting the full PNG data.
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
                    f"\033_Ga=T,f=100,q=2,i={_KITTY_IMG_ID},c={cols},r={rows},m={m};{chunk}\033\\"
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
